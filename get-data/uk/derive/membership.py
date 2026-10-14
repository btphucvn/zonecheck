"""Thành phần dân số của từng khu: mỗi khu (sector, district, postal_area, msoa, lad, region, nation, town)
gồm những phần LSOA nào, với tỉ lệ dân số → core.geo_area_link(child=lsoa, parent=khu, relation='overlaps',
weight = phần dân số của LSOA nằm trong khu, weight_basis='population').

Dân số mỗi postcode đang dùng = dân số OA (Census 2021 TS001) chia đều cho số postcode đang dùng trong OA.
Town (điểm, không có ranh giới) = các postcode trong bán kính theo loại: City 4 km, Town 2 km, Village 0,8 km,
Suburban Area 1 km.
"""
from __future__ import annotations

import logging

from ..loaders.base import LoadContext, LoadError
from .base import Step

log = logging.getLogger(__name__)

LEVEL_COLS = {"sector": "sector", "district": "district", "postal_area": "postal_area", "ward": "ward_code",
              "msoa": "msoa21_code", "lad": "lad_code", "region": "region_code"}
TOWN_RADIUS_M = {"City": 4000, "Town": 2000, "Suburban Area": 1000, "Village": 800}
EW_POPULATION_2021 = 59_597_542


class Membership(Step):
    name = "membership"
    needs_sources = ("onspd", "census2021", "os_open_names")
    description = "Dân số theo postcode → liên kết LSOA ↔ khu (overlaps, theo dân số) cho mọi cấp trang"

    def run(self, ctx: LoadContext) -> dict:
        ctx.sql("dân số mỗi postcode", """
            CREATE TEMP TABLE pc_pop ON COMMIT DROP AS
            SELECT p.postcode, p.oa21_code, p.lsoa21_code, p.sector, p.district, p.postal_area, p.msoa21_code, p.ward_code,
                   p.lad_code, p.region_code, p.country_code, p.geom,
                   v.value_num / count(*) OVER (PARTITION BY p.oa21_code) AS pop
            FROM mkt_uk.postcode p
            JOIN core.geo_area oa ON oa.market_code='uk' AND oa.level_code='oa' AND oa.code = p.oa21_code
            JOIN core.metric_value v ON v.market_code='uk' AND v.area_id = oa.id AND v.metric_id = 'uk.census21.ts001'
            WHERE p.status = 'live' AND p.geom IS NOT NULL""")
        ctx.conn.execute("CREATE INDEX ON pc_pop (lsoa21_code)")
        ctx.conn.execute("CREATE INDEX ON pc_pop USING gist (geom)")
        ctx.conn.execute("ANALYZE pc_pop")
        total = ctx.scalar("SELECT sum(pop) FROM pc_pop")
        lost = ctx.scalar("""SELECT sum(v.value_num) FROM core.metric_value v
            JOIN core.geo_area oa ON oa.id = v.area_id AND oa.level_code = 'oa'
            WHERE v.market_code='uk' AND v.metric_id='uk.census21.ts001'
              AND NOT EXISTS (SELECT 1 FROM mkt_uk.postcode p WHERE p.oa21_code = oa.code AND p.status='live' AND p.geom IS NOT NULL)""")
        log.info("    dân số phân bổ được: %s / %s (OA không có postcode đang dùng: %s)",
                 f"{total:,.0f}", f"{EW_POPULATION_2021:,}", f"{lost or 0:,.0f}")
        if abs(total + (lost or 0) - EW_POPULATION_2021) > 1000:
            raise LoadError(f"Tổng dân số OA ({total + (lost or 0):,.0f}) lệch Census E&W {EW_POPULATION_2021:,}")
        if (lost or 0) > EW_POPULATION_2021 * 0.005:
            raise LoadError(f"Quá nhiều dân số ở OA không có postcode: {lost:,.0f}")

        ctx.sql("dân số LSOA (tổng postcode)", """
            CREATE TEMP TABLE lsoa_pop ON COMMIT DROP AS
            SELECT a.id AS lsoa_id, a.code, sum(pc.pop) AS pop
            FROM pc_pop pc JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='lsoa' AND a.code = pc.lsoa21_code
            GROUP BY a.id, a.code""")
        ctx.conn.execute("CREATE INDEX ON lsoa_pop (code)")
        ctx.conn.execute("CREATE INDEX ON lsoa_pop (lsoa_id)")
        ctx.conn.execute("ANALYZE lsoa_pop")
        ctx.sql("xoá liên kết thành phần cũ", """
            DELETE FROM core.geo_area_link l USING core.geo_area c
            WHERE l.child_id = c.id AND c.level_code = 'lsoa' AND l.relation = 'overlaps' AND l.weight_basis = 'population'""")
        stats = {}
        for level, col in LEVEL_COLS.items():
            n = ctx.sql(f"thành phần {level}", f"""
                INSERT INTO core.geo_area_link (child_id, parent_id, relation, weight, weight_basis)
                SELECT lp.lsoa_id, a.id, 'overlaps', least(1, sum(pc.pop) / nullif(lp.pop, 0)), 'population'
                FROM pc_pop pc
                JOIN lsoa_pop lp ON lp.code = pc.lsoa21_code
                JOIN core.geo_area a ON a.market_code='uk' AND a.level_code=%s AND a.code = pc.{col}
                GROUP BY lp.lsoa_id, lp.pop, a.id
                HAVING sum(pc.pop) > 0""", (level,))
            stats[level] = n
            # mỗi LSOA phải được chia trọn vẹn (Σ trọng số ≈ 1) ở các cấp phân hoạch đầy đủ
            bad = ctx.scalar("""SELECT count(*) FROM (SELECT l.child_id, sum(l.weight) w FROM core.geo_area_link l
                JOIN core.geo_area p ON p.id = l.parent_id AND p.level_code = %s
                WHERE l.relation='overlaps' AND l.weight_basis='population' GROUP BY 1) x WHERE abs(w - 1) > 0.01""",
                (level,))
            if bad:
                raise LoadError(f"{level}: {bad} LSOA có tổng trọng số ≠ 1")
        # nation (E/W) từ mã quốc gia của postcode
        n = ctx.sql("thành phần nation", """
            INSERT INTO core.geo_area_link (child_id, parent_id, relation, weight, weight_basis)
            SELECT lp.lsoa_id, a.id, 'overlaps', 1, 'population'
            FROM lsoa_pop lp JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='nation'
                 AND a.code = CASE left(lp.code, 1) WHEN 'E' THEN 'E92000001' WHEN 'W' THEN 'W92000004' END""")
        stats["nation"] = n
        # town: postcode trong bán kính quanh điểm trung tâm
        radius = "CASE t.attrs->>'local_type' " + " ".join(
            f"WHEN '{k}' THEN {v}" for k, v in TOWN_RADIUS_M.items()) + " END"
        n = ctx.sql("thành phần town (bán kính)", f"""
            INSERT INTO core.geo_area_link (child_id, parent_id, relation, weight, weight_basis)
            SELECT lp.lsoa_id, t.id, 'overlaps', least(1, sum(pc.pop) / nullif(lp.pop, 0)), 'population'
            FROM core.geo_area t
            -- lọc thô bằng geometry (dùng GiST, 1° ≥ ~55 km ở vĩ độ UK) rồi mới lọc chính xác bằng geography
            JOIN pc_pop pc ON ST_DWithin(pc.geom, t.centroid, ({radius}) / 55000.0)
                          AND ST_DWithin(pc.geom::geography, t.centroid::geography, {radius})
            JOIN lsoa_pop lp ON lp.code = pc.lsoa21_code
            WHERE t.market_code='uk' AND t.level_code='town' AND t.is_active
            GROUP BY lp.lsoa_id, lp.pop, t.id
            HAVING sum(pc.pop) > 0""")
        stats["town"] = n
        towns_with = ctx.scalar("""SELECT count(DISTINCT parent_id) FROM core.geo_area_link l JOIN core.geo_area t
            ON t.id = l.parent_id AND t.level_code='town' WHERE l.relation='overlaps'""")
        towns_ew = ctx.scalar("""SELECT count(*) FROM core.geo_area WHERE level_code='town' AND is_active
            AND attrs->>'country' IN ('England', 'Wales')""")
        log.info("    town có thành phần dân số: %s / %s town ở E&W", towns_with, towns_ew)
        if towns_with < towns_ew * 0.97:
            raise LoadError(f"Chỉ {towns_with}/{towns_ew} town có dân số trong bán kính")
        # lưu dân số ước tính cho các cấp postal/town vào geo_area.population (dùng cho tỉ lệ / 1.000 dân)
        ctx.sql("geo_area.population theo thành phần", """
            UPDATE core.geo_area a SET population = round(x.pop), population_year = 2021
            FROM (SELECT l.parent_id, sum(l.weight * lp.pop) pop FROM core.geo_area_link l
                  JOIN lsoa_pop lp ON lp.lsoa_id = l.child_id
                  WHERE l.relation='overlaps' AND l.weight_basis='population' GROUP BY 1) x
            -- chỉ cập nhật khi đổi giá trị (tránh ghi lại hàng chục nghìn dòng geo_area có geometry lớn)
            WHERE a.id = x.parent_id AND a.population IS DISTINCT FROM round(x.pop)""")
        ctx.sql("geo_area.population LSOA", """UPDATE core.geo_area a SET population = round(lp.pop), population_year = 2021
                                              FROM lsoa_pop lp WHERE a.id = lp.lsoa_id""")
        ew = ctx.scalar("SELECT sum(population) FROM core.geo_area WHERE level_code = 'nation' AND code IN ('E92000001','W92000004')")
        log.info("    dân số nation E+W sau phân bổ: %s", f"{ew:,}")
        if abs(ew - total) > 1000:
            raise LoadError(f"Dân số nation ({ew:,}) ≠ tổng postcode ({total:,.0f})")
        return {"population_allocated": round(total), "links": stats}
