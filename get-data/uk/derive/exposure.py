"""Phơi nhiễm vùng: tỉ lệ dân (theo postcode) nằm trong vùng lũ / quy hoạch / bảo tồn → core.area_zone_exposure
và metric uk.zone.<loại>_share (LSOA; bước rollup đưa lên các cấp khác).
"""
from __future__ import annotations

import logging
from datetime import date

from ..loaders.base import LoadContext, LoadError
from ..loaders.metrics import register_metric
from .base import Step

log = logging.getLogger(__name__)

ZONES = {  # zone_type(s) → (metric key, tên, category, direction)
    ("flood.zone3",): ("flood_zone3", "Residents in Flood Zone 3 (rivers and sea, high probability)", "risk", -1),
    ("flood.zone2", "flood.zone3"): ("flood_zone2plus", "Residents in Flood Zone 2 or 3 (rivers and sea)", "risk", -1),
    ("planning.conservation_area",): ("conservation_area", "Residents in a conservation area", "planning", 0),
    ("planning.green_belt",): ("green_belt", "Residents in green belt", "planning", 0),
    ("planning.article4",): ("article4", "Residents in an Article 4 direction area", "planning", 0),
    ("nature.national_park",): ("national_park", "Residents in a National Park", "planning", 0),
    ("nature.national_landscape",): ("national_landscape", "Residents in a National Landscape (AONB)", "planning", 0),
}


class Exposure(Step):
    name = "exposure"
    depends_on = ("membership",)
    needs_sources = ("ea_flood_zones", "planning_data", "natural_england")
    description = "Tỉ lệ dân trong Flood Zone 2/3, conservation area, green belt, Article 4, National Park, AONB"

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
        # Polygon lũ dọc sông rất dài/nhiều đỉnh: kiểm tra điểm-trong-polygon trực tiếp ~20 ms/postcode (gần 1 ngày
        # cho 1,6 triệu postcode). Chia nhỏ (ST_Subdivide ≤ 255 đỉnh) vào bảng tạm có GiST → nhanh ~180 lần.
        flags = []
        for types, (key, *_rest) in ZONES.items():
            ctx.sql(f"chia nhỏ polygon {key}", f"""
                CREATE TEMP TABLE zsub_{key} ON COMMIT DROP AS
                SELECT ST_Subdivide(geom, 255) AS geom FROM core.zone
                WHERE market_code='uk' AND type_code = ANY(%s)""", (list(types),))
            ctx.conn.execute(f"CREATE INDEX ON zsub_{key} USING gist (geom)")
            ctx.conn.execute(f"ANALYZE zsub_{key}")
            flags.append(f"EXISTS (SELECT 1 FROM zsub_{key} z WHERE ST_Intersects(z.geom, p.geom)) AS in_{key}")
        bad = ctx.scalar(f"""SELECT count(*) FROM core.zone WHERE market_code='uk'
            AND type_code = ANY(%s) AND NOT ST_CoveredBy(geom, ST_MakeEnvelope(-9, 49.5, 2.5, 61.5, 4326))""",
                         ([t for ts in ZONES for t in ts],))
        if bad:
            raise LoadError(f"{bad} polygon vùng vượt khung UK — dữ liệu hỏng, sửa trước khi tính phơi nhiễm")
        ctx.sql("postcode ∩ vùng", f"""
            CREATE TEMP TABLE pc_zone ON COMMIT DROP AS
            SELECT p.lsoa21_code, p.pop, {", ".join(flags)} FROM pcs p""")
        n_types = {t: ctx.scalar("SELECT count(*) FROM core.zone WHERE type_code=%s", (t,))
                   for types in ZONES for t in types}
        missing = [t for t, n in n_types.items() if not n]
        if missing:
            raise LoadError(f"Chưa có polygon cho loại vùng: {missing}")

        for types, (key, name, cat, direction) in ZONES.items():
            register_metric(ctx, f"uk.zone.{key}_share", category=cat, dataset=None, value_type="percent", unit="%",
                            decimals=1, direction=direction, period_type="snapshot", native_level="lsoa",
                            aggregation="weighted_mean", scope="uk.england", name=name,
                            scorable=direction != 0,
                            description="Tỉ lệ dân (ước tính theo postcode) có vị trí nằm trong vùng")
        ids = [f"uk.zone.{k}_share" for k, *_ in ZONES.values()]
        ctx.sql("xoá giá trị cũ", "DELETE FROM core.metric_value WHERE market_code='uk' AND metric_id = ANY(%s)", (ids,))
        lateral = ", ".join(f"('uk.zone.{k}_share', z.in_{k})" for k, *_ in ZONES.values())
        n = ctx.sql("tỉ lệ dân theo LSOA", f"""
            INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size)
            -- coalesce: LSOA không có ai trong vùng phải là 0, không phải NULL (NULL làm rollup bỏ qua LSOA đó
            -- → khu hỗn hợp bị thổi phồng tỉ lệ, khu không có ai trong vùng thì mất giá trị)
            SELECT 'uk', a.id, m.metric_id, %s, 100.0 * coalesce(sum(z.pop) FILTER (WHERE m.flag), 0) / sum(z.pop), count(*)
            FROM pc_zone z JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='lsoa' AND a.code = z.lsoa21_code
            CROSS JOIN LATERAL (VALUES {lateral}) m(metric_id, flag)
            WHERE left(z.lsoa21_code, 1) = 'E'
            GROUP BY a.id, m.metric_id HAVING sum(z.pop) > 0""", (period,))
        nulls = ctx.scalar("SELECT count(*) FROM core.metric_value WHERE metric_id = ANY(%s) AND value_num IS NULL", (ids,))
        if nulls:
            raise LoadError(f"{nulls} giá trị tỉ lệ vùng bị NULL (phải là 0 khi không có ai trong vùng)")
        # area_zone_exposure (LSOA) cho trang báo cáo
        ctx.sql("xoá area_zone_exposure cũ", "DELETE FROM core.area_zone_exposure WHERE zone_type_code = ANY(%s)",
                ([t[0] for t in ZONES if len(t) == 1],))
        single = {t[0]: k for t, (k, *_) in ZONES.items() if len(t) == 1}
        lateral2 = ", ".join(f"('{t}', z.in_{k})" for t, k in single.items())
        ctx.sql("area_zone_exposure LSOA", f"""
            INSERT INTO core.area_zone_exposure (area_id, zone_type_code, intersects, share_of_addresses)
            SELECT a.id, m.zt, bool_or(m.flag), coalesce(sum(z.pop) FILTER (WHERE m.flag), 0) / sum(z.pop)
            FROM pc_zone z JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='lsoa' AND a.code = z.lsoa21_code
            CROSS JOIN LATERAL (VALUES {lateral2}) m(zt, flag)
            WHERE left(z.lsoa21_code, 1) = 'E'
            GROUP BY a.id, m.zt HAVING sum(z.pop) > 0""")

        # ---- kiểm tra hợp lý: tỉ lệ dân England
        eng = dict(ctx.conn.execute(f"""SELECT m.k, 100.0 * sum(z.pop) FILTER (WHERE m.flag) / sum(z.pop)
            FROM pc_zone z CROSS JOIN LATERAL (VALUES {", ".join(f"('{k}', z.in_{k})" for k, *_ in ZONES.values())}) m(k, flag)
            WHERE left(z.lsoa21_code, 1) = 'E' GROUP BY 1""").fetchall())
        log.info("    %% dân England trong vùng: %s", {k: round(v, 2) for k, v in eng.items()})
        if not 2 <= eng["flood_zone3"] <= 15:
            raise LoadError(f"Tỉ lệ dân trong Flood Zone 3 bất thường: {eng['flood_zone3']:.1f}%")
        if not eng["flood_zone3"] <= eng["flood_zone2plus"] <= 25:
            raise LoadError(f"Tỉ lệ Flood Zone 2+3 bất thường: {eng['flood_zone2plus']:.1f}% (phải ≥ Zone 3 và ≤ 25%)")
        too_big = {k: v for k, v in eng.items() if v > 40}
        if too_big:  # không loại vùng nào chứa > 40% dân England — dấu hiệu polygon hỏng/trùm rộng
            raise LoadError(f"Tỉ lệ dân trong vùng quá cao (polygon hỏng?): {too_big}")
        if not 0.4 <= eng["national_park"] <= 2:  # ~ 450 nghìn dân trong National Parks England (~0,8%)
            raise LoadError(f"Tỉ lệ dân trong National Park bất thường: {eng['national_park']:.2f}%")
        return {"values": n, "england_share_pct": {k: round(v, 2) for k, v in eng.items()}}
