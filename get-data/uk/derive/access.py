"""Khả năng tiếp cận dịch vụ: tính cho từng postcode đang dùng (E&W), trung bình theo dân số lên LSOA.

Khoảng cách đường chim bay (m) tới điểm gần nhất từng loại; số điểm trong bán kính; chất lượng trường gần nhất.
Bước rollup đưa các chỉ số LSOA lên mọi cấp trang. Trang postcode tính trực tiếp lúc hiển thị (KNN nhanh).
"""
from __future__ import annotations

import logging
from datetime import date

from ..loaders.base import LoadContext, LoadError
from ..loaders.metrics import register_metric
from .base import Step

log = logging.getLogger(__name__)

NEAREST = {  # key → (điều kiện POI, tên)
    "gp": ("type_code = 'health.gp'", "GP practice"),
    "pharmacy": ("type_code = 'health.pharmacy'", "pharmacy"),
    "primary": ("type_code IN ('school.primary', 'school.all_through')", "primary school"),
    "secondary": ("type_code IN ('school.secondary', 'school.all_through')", "secondary school"),
    "rail": ("type_code IN ('station.rail', 'station.metro')", "rail / tube / tram station"),
    "supermarket": ("type_code = 'shop.supermarket'", "supermarket"),
}
COUNTS = {  # key → (điều kiện, bán kính m, tên)
    "bus_stops_500m": ("type_code = 'stop.bus'", 500, "Bus stops within 500 m"),
    "food_1km": ("type_code IN ('food.restaurant', 'food.pub', 'food.takeaway')", 1000, "Restaurants, cafes, pubs and takeaways within 1 km"),
}
SANITY_M = {"gp": (300, 3000), "rail": (800, 10000), "supermarket": (300, 4000), "primary": (200, 2500),
            "secondary": (500, 5000), "pharmacy": (200, 3000), "park": (100, 2500)}


class Access(Step):
    name = "access"
    depends_on = ("membership",)
    needs_sources = ("gias", "naptan", "nhs_ods", "fsa", "os_open_greenspace", "dfe_performance")
    description = "Khoảng cách tới GP/trường/ga/siêu thị/công viên, số tiện ích quanh nhà, chất lượng trường gần nhất"

    def run(self, ctx: LoadContext) -> dict:
        period = date.today().replace(day=1)
        ctx.sql("postcode + dân số (E&W)", """
            CREATE TEMP TABLE pcs ON COMMIT DROP AS
            SELECT p.postcode, p.lsoa21_code, p.geom,
                   v.value_num / count(*) OVER (PARTITION BY p.oa21_code) AS pop
            FROM mkt_uk.postcode p
            JOIN core.geo_area oa ON oa.market_code='uk' AND oa.level_code='oa' AND oa.code = p.oa21_code
            JOIN core.metric_value v ON v.market_code='uk' AND v.area_id = oa.id AND v.metric_id='uk.census21.ts001'
            WHERE p.status='live' AND p.geom IS NOT NULL""")
        ctx.conn.execute("CREATE INDEX ON pcs USING gist (geom)")
        ctx.conn.execute("ANALYZE pcs")
        # bảng điểm riêng từng loại (index GiST riêng → KNN không phải lọc qua hàng trăm nghìn điểm dừng xe buýt)
        for key, (cond, _) in {**NEAREST, **{k: (c, n) for k, (c, _, n) in COUNTS.items()}}.items():
            ctx.conn.execute(f"""CREATE TEMP TABLE poi_{key} ON COMMIT DROP AS
                SELECT id, geom FROM core.poi WHERE market_code='uk' AND status='open' AND {cond}""")
            ctx.conn.execute(f"CREATE INDEX ON poi_{key} USING gist (geom)")
            ctx.conn.execute(f"ANALYZE poi_{key}")
        ctx.conn.execute("""CREATE TEMP TABLE park ON COMMIT DROP AS SELECT id, geom FROM core.zone
                            WHERE market_code='uk' AND type_code IN ('greenspace.park', 'greenspace.playing_field')""")
        ctx.conn.execute("CREATE INDEX ON park USING gist (geom)")
        ctx.conn.execute("ANALYZE park")
        # trường có kết quả gần nhất (chất lượng): KS2 % đạt chuẩn, KS4 Attainment 8 — năm mới nhất
        for key, metric in (("ks2", "uk.ks2.rwm_expected_pct"), ("ks4", "uk.ks4.attainment8")):
            ctx.conn.execute(f"""CREATE TEMP TABLE school_{key} ON COMMIT DROP AS
                SELECT p.id, p.geom, v.value_num FROM core.poi p
                JOIN core.poi_metric_value v ON v.poi_id = p.id AND v.metric_id = %s
                     AND v.period = (SELECT max(period) FROM core.poi_metric_value WHERE metric_id = %s)
                WHERE p.status = 'open' AND v.value_num IS NOT NULL""", (metric, metric))
            ctx.conn.execute(f"CREATE INDEX ON school_{key} USING gist (geom)")
            ctx.conn.execute(f"ANALYZE school_{key}")

        near = ",\n".join(
            f"(SELECT ST_Distance(p.geom::geography, x.geom::geography) FROM poi_{k} x ORDER BY x.geom <-> p.geom LIMIT 1) AS d_{k}"
            for k in NEAREST)
        counts = ",\n".join(
            f"(SELECT count(*) FROM poi_{k} x WHERE ST_DWithin(x.geom, p.geom, {r} / 55000.0) "
            f"AND ST_DWithin(x.geom::geography, p.geom::geography, {r})) AS n_{k}" for k, (_, r, _) in COUNTS.items())
        ctx.sql("tính cho từng postcode (KNN)", f"""
            CREATE TEMP TABLE pc_access ON COMMIT DROP AS
            SELECT p.postcode, p.lsoa21_code, p.pop,
                   {near},
                   (SELECT min(ST_Distance(p.geom::geography, x.geom::geography))
                    FROM (SELECT geom FROM park ORDER BY geom <-> p.geom LIMIT 5) x) AS d_park,
                   {counts},
                   (SELECT avg(value_num) FROM (SELECT value_num FROM school_ks2 ORDER BY geom <-> p.geom LIMIT 3) s) AS q_ks2,
                   (SELECT avg(value_num) FROM (SELECT value_num FROM school_ks4 ORDER BY geom <-> p.geom LIMIT 3) s) AS q_ks4
            FROM pcs p WHERE left(p.lsoa21_code, 1) IN ('E', 'W')""")

        cols = {f"d_{k}": (f"uk.access.{k}_dist_m", f"Distance to nearest {n}", "number", "m", -1)
                for k, (_, n) in NEAREST.items()}
        cols["d_park"] = ("uk.access.park_dist_m", "Distance to nearest park or playing field", "number", "m", -1)
        cols.update({f"n_{k}": (f"uk.access.{k}", n, "count", None, 1) for k, (_, _, n) in COUNTS.items()})
        cols["q_ks2"] = ("uk.schools.primary_quality", "Nearby primary schools: % reaching expected standard (3 nearest)", "percent", "%", 1)
        cols["q_ks4"] = ("uk.schools.secondary_quality", "Nearby secondary schools: Attainment 8 (3 nearest)", "number", None, 1)
        for col, (mid, name, vt, unit, direction) in cols.items():
            register_metric(ctx, mid, category="education" if mid.startswith("uk.schools") else
                            ("transport" if "rail" in mid or "bus" in mid else "amenities"),
                            dataset=None, value_type=vt, unit=unit, decimals=0 if vt != "percent" else 1,
                            direction=direction, period_type="snapshot", native_level="lsoa",
                            aggregation="weighted_mean", scope="uk.england" if mid.startswith("uk.schools") else "uk.ew",
                            name=name, description="Trung bình theo dân số của các postcode trong khu (đường chim bay)")
        ids = [c[0] for c in cols.values()]
        ctx.sql("xoá giá trị cũ", "DELETE FROM core.metric_value WHERE market_code='uk' AND metric_id = ANY(%s)", (ids,))
        lateral = ", ".join(f"('{mid}', {col})" for col, (mid, *_) in cols.items())
        n = ctx.sql("trung bình theo dân số → LSOA", f"""
            INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size)
            SELECT 'uk', a.id, m.metric_id, %s, sum(m.v * x.pop) / nullif(sum(x.pop) FILTER (WHERE m.v IS NOT NULL), 0),
                   count(*)
            FROM pc_access x
            JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='lsoa' AND a.code = x.lsoa21_code
            CROSS JOIN LATERAL (VALUES {lateral}) m(metric_id, v)
            GROUP BY a.id, m.metric_id
            HAVING sum(x.pop) FILTER (WHERE m.v IS NOT NULL) > 0""", (period,))

        # ---- kiểm tra hợp lý: trung bình toàn E&W theo dân số
        nat = dict(ctx.conn.execute(f"""SELECT m.metric_id, sum(m.v * x.pop) / sum(x.pop) FILTER (WHERE m.v IS NOT NULL)
            FROM pc_access x CROSS JOIN LATERAL (VALUES {lateral}) m(metric_id, v) GROUP BY 1""").fetchall())
        log.info("    trung bình E&W theo dân số: %s", {k.split(".")[-1]: round(v, 1) for k, v in nat.items() if v is not None})
        for key, (lo, hi) in SANITY_M.items():
            v = nat.get(f"uk.access.{key}_dist_m")
            if v is None or not lo <= v <= hi:
                raise LoadError(f"Khoảng cách trung bình tới {key} bất thường: {v} m (kỳ vọng {lo}–{hi})")
        if not 50 <= (nat.get("uk.schools.primary_quality") or 0) <= 80:
            raise LoadError(f"Chất lượng tiểu học trung bình bất thường: {nat.get('uk.schools.primary_quality')}")
        n_lsoa = ctx.scalar("""SELECT count(DISTINCT area_id) FROM core.metric_value WHERE metric_id='uk.access.gp_dist_m'""")
        lsoa_ew = ctx.scalar("SELECT count(*) FROM core.geo_area WHERE level_code='lsoa' AND is_active")
        if n_lsoa < lsoa_ew * 0.995:
            raise LoadError(f"Chỉ {n_lsoa}/{lsoa_ew} LSOA có chỉ số tiếp cận")
        return {"values": n, "national_means": {k: round(v, 1) for k, v in nat.items() if v is not None}}
