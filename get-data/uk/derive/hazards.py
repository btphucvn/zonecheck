"""Rủi ro bổ sung: tỉ lệ dân (theo postcode) trong/gần vùng radon, mỏ than, GeoSure, bãi rác, lũ đã xảy ra, xói lở bờ biển,
AQMA → uk.zone.<khoá>_share (LSOA); khí hậu 1991–2020 tại postcode → uk.climate.<khoá> (trung bình theo dân, LSOA).

Hình học tính trên British National Grid (EPSG:27700, mét): khoảng cách đệm (bãi rác) dùng ST_DWithin trên toạ độ phẳng,
có index; vùng được ST_Subdivide (≤ 255 đỉnh) như bước exposure để kiểm tra điểm-trong-polygon nhanh.
"""
from __future__ import annotations

import logging
from datetime import date

from ..loaders.base import LoadContext, LoadError
from ..loaders.metrics import register_metric
from .base import Step

log = logging.getLogger(__name__)

# khoá → (loại vùng, mức tối thiểu level_rank hoặc None, đệm m, phạm vi so sánh, tên, category, direction, tính điểm)
HAZARDS = {
    "radon_1pct": (["radon.atlas"], 2, 0, "uk.ew", "Residents in a radon affected area (1%+ of homes above the action level)", "risk", -1, True),
    "radon_5pct": (["radon.atlas"], 4, 0, "uk.ew", "Residents where 5%+ of homes are above the radon action level", "risk", -1, False),
    "coal_reporting": (["coal.high_risk", "coal.low_risk"], None, 0, "uk.ew", "Residents in a coal mining reporting area", "risk", -1, False),
    "coal_high_risk": (["coal.high_risk"], None, 0, "uk.ew", "Residents in a coal mining development high risk area", "risk", -1, True),
    "shrink_swell_sig": (["geo.shrink_swell"], 3, 0, "uk.ew", "Residents in an area of significant shrink–swell clay (subsidence) susceptibility", "risk", -1, True),
    "landslide_mod": (["geo.landslides"], 2, 0, "uk.ew", "Residents in an area of moderate or significant landslide susceptibility", "risk", -1, False),
    "soluble_rocks_mod": (["geo.soluble_rocks"], 2, 0, "uk.ew", "Residents in an area of moderate or significant soluble rock (sinkhole) susceptibility", "risk", -1, False),
    "compressible_mod": (["geo.compressible_ground"], 2, 0, "uk.ew", "Residents in an area of moderate or significant compressible ground", "risk", -1, False),
    "mining_non_coal_mod": (["geo.mining_non_coal"], 2, 0, "uk.ew", "Residents in an area of moderate or significant non-coal mining hazard", "risk", -1, False),
    "landfill_historic_250m": (["risk.landfill_historic", "risk.landfill_historic_wales"], None, 250, "uk.ew", "Residents within 250 m of a historic landfill site", "risk", -1, True),
    "landfill_authorised_500m": (["risk.landfill_authorised"], None, 500, "uk.england", "Residents within 500 m of an operating (permitted) landfill site", "risk", -1, False),
    "flood_historic": (["flood.historic", "flood.wales_historic"], None, 0, "uk.ew", "Residents in an area that has flooded before (EA / NRW historic flood maps)", "risk", -1, True),
    "wales_flood_zone3": (["flood.wales_zone3"], None, 0, "uk.wales", "Residents in Flood Zone 3 (Wales, rivers and sea)", "risk", -1, True),
    "wales_flood_zone2plus": (["flood.wales_zone2", "flood.wales_zone3"], None, 0, "uk.wales", "Residents in Flood Zone 2 or 3 (Wales, rivers and sea)", "risk", -1, False),
    "wales_rs_high": (["flood.wales_rivers", "flood.wales_sea"], 3, 0, "uk.wales", "Residents at high risk of flooding from rivers or the sea (Wales)", "risk", -1, False),
    "coastal_erosion_2105": (["coast.erosion_2105", "coast.ground_instability"], None, 0, "uk.england", "Residents in a coastal erosion or instability zone by 2105", "risk", -1, False),
    "aqma": (["env.aqma"], None, 0, "uk.england", "Residents in an Air Quality Management Area", "environment", -1, False),
}
# khoá → (loại vùng, tên, đơn vị, số lẻ, direction, khoảng hợp lý trung bình England)
CLIMATE = {
    "tas": ("climate.tas", "Mean annual temperature (1991–2020)", "°C", 1, 0, (8, 12)),
    "tasmax": ("climate.tasmax", "Mean daily maximum temperature (1991–2020)", "°C", 1, 0, (11, 16)),
    "tasmin": ("climate.tasmin", "Mean daily minimum temperature (1991–2020)", "°C", 1, 0, (4, 8)),
    "rainfall": ("climate.rainfall", "Annual rainfall (1991–2020)", "mm", 0, 0, (550, 1100)),
    "airfrost_days": ("climate.airfrost_days", "Days of air frost per year (1991–2020)", "days", 0, 0, (20, 70)),
    "summer_days": ("climate.summer_days", "Summer days above 25 °C per year (1991–2020)", "days", 0, 0, (3, 30)),
    "rain10mm_days": ("climate.rain10mm_days", "Days with 10 mm or more rain per year (1991–2020)", "days", 0, 0, (12, 40)),
    "icing_days": ("climate.icing_days", "Icing days (max below 0 °C) per year (1991–2020)", "days", 1, 0, (0, 10)),
}


class Hazards(Step):
    name = "hazards"
    depends_on = ("membership",)
    needs_sources = ("bgs_radon", "coal_authority", "nrw_flood", "bgs_geosure_hex", "bgs_mining_hazard", "ea_landfill",
                     "ea_flood_history", "ea_coastal_erosion", "planning_data_extra", "haduk_grid")
    description = "Tỉ lệ dân trong vùng radon/mỏ/GeoSure/bãi rác/lũ đã xảy ra/xói lở/AQMA + khí hậu 1991–2020 theo LSOA"

    def run(self, ctx: LoadContext) -> dict:
        period = date.today().replace(day=1)
        ctx.sql("postcode + dân số (E&W, BNG)", """
            CREATE TEMP TABLE hz_pc ON COMMIT DROP AS
            SELECT p.postcode, p.lsoa21_code, ST_Transform(p.geom, 27700) AS g,
                   v.value_num / count(*) OVER (PARTITION BY p.oa21_code) AS pop
            FROM mkt_uk.postcode p
            JOIN core.geo_area oa ON oa.market_code='uk' AND oa.level_code='oa' AND oa.code = p.oa21_code
            JOIN core.metric_value v ON v.market_code='uk' AND v.area_id = oa.id AND v.metric_id='uk.census21.ts001'
            WHERE p.status='live' AND p.geom IS NOT NULL""")
        ctx.conn.execute("CREATE INDEX ON hz_pc USING gist (g)")

        missing = [t for k, (types, *_r) in HAZARDS.items() for t in types
                   if not ctx.scalar("SELECT 1 FROM core.zone WHERE market_code='uk' AND type_code=%s LIMIT 1", (t,))]
        missing += [zt for zt, *_r in CLIMATE.values()
                    if not ctx.scalar("SELECT 1 FROM core.zone WHERE market_code='uk' AND type_code=%s LIMIT 1", (zt,))]
        if missing:
            raise LoadError(f"Chưa có vùng cho: {sorted(set(missing))} — chạy loader tương ứng trước")

        flags = []
        for k, (types, min_rank, buf, *_r) in HAZARDS.items():
            ctx.sql(f"chia nhỏ vùng {k}", f"""
                CREATE TEMP TABLE hz_{k} ON COMMIT DROP AS
                SELECT ST_Subdivide(ST_Transform(geom, 27700), 255) AS g FROM core.zone
                WHERE market_code='uk' AND type_code = ANY(%s) {"AND level_rank >= %s" if min_rank else ""}""",
                    (types, min_rank) if min_rank else (types,))
            ctx.conn.execute(f"CREATE INDEX ON hz_{k} USING gist (g)")
            ctx.conn.execute(f"ANALYZE hz_{k}")
            test = f"ST_DWithin(z.g, p.g, {buf})" if buf else "ST_Intersects(z.g, p.g)"
            flags.append(f"EXISTS (SELECT 1 FROM hz_{k} z WHERE {test}) AS f_{k}")
        ctx.sql("postcode × vùng rủi ro", f"CREATE TEMP TABLE hz_flag ON COMMIT DROP AS SELECT p.lsoa21_code, p.pop, {', '.join(flags)} FROM hz_pc p")

        # khí hậu: giá trị ô lưới chứa postcode (ô lưới không chồng nhau → lấy 1)
        cvals = []
        for k, (zt, *_r) in CLIMATE.items():
            ctx.sql(f"ô khí hậu {k}", f"""
                CREATE TEMP TABLE hzc_{k} ON COMMIT DROP AS
                SELECT ST_Transform(geom, 27700) AS g, nullif(name, '')::float8 AS v FROM core.zone
                WHERE market_code='uk' AND type_code = %s AND nullif(name, '') IS NOT NULL""", (zt,))
            ctx.conn.execute(f"CREATE INDEX ON hzc_{k} USING gist (g)")
            ctx.conn.execute(f"ANALYZE hzc_{k}")
            # ô chứa postcode; postcode ven biển/ô lưới thiếu giá trị → ô gần nhất trong 15 km (KNN theo index GiST)
            cvals.append(f"(SELECT z.v FROM hzc_{k} z WHERE ST_DWithin(z.g, p.g, 15000) ORDER BY z.g <-> p.g LIMIT 1) AS c_{k}")
        ctx.sql("postcode × khí hậu", f"CREATE TEMP TABLE hz_clim ON COMMIT DROP AS SELECT p.lsoa21_code, p.pop, {', '.join(cvals)} FROM hz_pc p")

        # ---- kiểm tra hợp lý trên toàn England
        eng = dict(ctx.conn.execute(f"""SELECT m.k, 100.0 * coalesce(sum(f.pop) FILTER (WHERE m.f), 0) / sum(f.pop) FROM hz_flag f
            CROSS JOIN LATERAL (VALUES {", ".join(f"('{k}', f.f_{k})" for k in HAZARDS)}) m(k, f)
            WHERE left(f.lsoa21_code, 1) = 'E' GROUP BY 1""").fetchall())
        log.info("    %% dân England: %s", {k: round(v, 2) for k, v in eng.items()})
        wal = dict(ctx.conn.execute(f"""SELECT m.k, 100.0 * coalesce(sum(f.pop) FILTER (WHERE m.f), 0) / sum(f.pop) FROM hz_flag f
            CROSS JOIN LATERAL (VALUES {", ".join(f"('{k}', f.f_{k})" for k in HAZARDS if k.startswith('wales_'))}) m(k, f)
            WHERE left(f.lsoa21_code, 1) = 'W' GROUP BY 1""").fetchall())
        log.info("    %% dân Wales: %s", {k: round(v, 2) for k, v in wal.items()})
        # NRW: ~245 nghìn cơ sở (≈ 1/8) ở vùng có rủi ro lũ sông/biển; Flood Zone 3 cỡ 5–15% dân
        if not (2 <= wal["wales_flood_zone3"] <= 25 and wal["wales_flood_zone3"] <= wal["wales_flood_zone2plus"]):
            raise LoadError(f"Tỉ lệ dân Wales trong Flood Zone bất thường: {wal}")
        eng = {k: v for k, v in eng.items() if not k.startswith("wales_")}
        too_big = {k: v for k, v in eng.items() if v > 60}
        if too_big:
            raise LoadError(f"Tỉ lệ dân trong vùng quá cao (polygon hỏng?): {too_big}")
        if not 2 <= eng["coal_reporting"] <= 40:  # ~ 1/4 dân England sống trên vùng than cũ (Coal Authority)
            raise LoadError(f"Tỉ lệ dân vùng mỏ than bất thường: {eng['coal_reporting']:.1f}%")
        if not eng["coal_high_risk"] < eng["coal_reporting"]:
            raise LoadError("Vùng rủi ro cao mỏ than phải nhỏ hơn cả vùng báo cáo")
        # atlas lấy mức cao nhất trong mỗi ô 1 km nên thiên cao: ~43% dân England ở ô có ≥ 1% nhà vượt ngưỡng
        if not (eng["radon_5pct"] < eng["radon_1pct"] and 3 <= eng["radon_1pct"] <= 60):
            raise LoadError(f"Tỉ lệ radon bất thường: {eng['radon_1pct']:.1f}% / {eng['radon_5pct']:.1f}%")
        # đối chiếu định hướng: Cornwall (đá granite) phải có tỉ lệ radon cao hơn hẳn England
        cw = ctx.scalar("""SELECT 100.0 * sum(pop) FILTER (WHERE f_radon_1pct) / sum(pop) FROM hz_flag
            WHERE lsoa21_code IN (SELECT lsoa21_code FROM mkt_uk.postcode WHERE lad_code = 'E06000052')""")
        log.info("    Cornwall: %.1f%% dân trong vùng radon ≥ 1%%", cw or 0)
        if cw is None or cw < 2 * eng["radon_1pct"] or cw < 50:
            raise LoadError(f"Kiểm tra định hướng radon thất bại: Cornwall {cw} so với England {eng['radon_1pct']:.1f}%")
        clim = {r[0]: (r[1], r[2]) for r in ctx.conn.execute(f"""SELECT m.k,
                    sum(c.pop * m.v) FILTER (WHERE m.v IS NOT NULL) / sum(c.pop) FILTER (WHERE m.v IS NOT NULL),
                    count(*) FILTER (WHERE m.v IS NULL)::float / count(*) FROM hz_clim c
                    CROSS JOIN LATERAL (VALUES {", ".join(f"('{k}', c.c_{k})" for k in CLIMATE)}) m(k, v)
                    WHERE left(c.lsoa21_code, 1) = 'E' GROUP BY 1""").fetchall()}
        log.info("    khí hậu trung bình England (theo dân), tỉ lệ postcode thiếu: %s",
                 {k: (round(v, 1), round(miss, 4)) for k, (v, miss) in clim.items()})
        for k, (v, miss) in clim.items():
            lo, hi = CLIMATE[k][5]
            if not lo <= v <= hi:
                raise LoadError(f"Khí hậu {k} trung bình England {v:.1f} ngoài khoảng hợp lý [{lo}, {hi}]")
            if miss > 0.01:
                raise LoadError(f"Khí hậu {k}: {miss:.1%} postcode không rơi vào ô lưới nào")

        # ---- ghi chỉ số
        for k, (types, _mr, buf, scope, name, cat, direction, scorable) in HAZARDS.items():
            register_metric(ctx, f"uk.zone.{k}_share", category=cat, dataset=None, value_type="percent", unit="%",
                            decimals=1, direction=direction, period_type="snapshot", native_level="lsoa",
                            aggregation="weighted_mean", scope=scope, name=name, scorable=scorable,
                            description=f"Share of residents (by postcode) {'within ' + str(buf) + ' m of' if buf else 'inside'} "
                                        f"zones: {', '.join(types)}")
        for k, (zt, name, unit, dec, direction, _r) in CLIMATE.items():
            register_metric(ctx, f"uk.climate.{k}", category="environment", dataset="uk.metoffice.haduk_grid",
                            value_type="number", unit=unit, decimals=dec, direction=direction, period_type="snapshot",
                            native_level="lsoa", aggregation="weighted_mean", scope="uk.ew", name=name, scorable=False,
                            description="Met Office HadUK-Grid 1991–2020 average for the grid cell of each postcode, weighted by residents")
        ids = [f"uk.zone.{k}_share" for k in HAZARDS] + [f"uk.climate.{k}" for k in CLIMATE]
        ctx.sql("xoá giá trị cũ", "DELETE FROM core.metric_value WHERE market_code='uk' AND metric_id = ANY(%s)", (ids,))
        scope_sql = {"uk.england": "left(f.lsoa21_code, 1) = 'E'", "uk.ew": "left(f.lsoa21_code, 1) IN ('E', 'W')",
                     "uk.wales": "left(f.lsoa21_code, 1) = 'W'"}
        n = 0
        for k, (_t, _mr, _b, scope, *_r) in HAZARDS.items():
            n += ctx.sql(f"tỉ lệ dân {k}", f"""
                INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size)
                SELECT 'uk', a.id, %s, %s, round((100.0 * coalesce(sum(f.pop) FILTER (WHERE f.f_{k}), 0) / sum(f.pop))::numeric, 2), count(*)
                FROM hz_flag f JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='lsoa' AND a.code = f.lsoa21_code
                WHERE {scope_sql[scope]} GROUP BY a.id HAVING sum(f.pop) > 0""", (f"uk.zone.{k}_share", period))
        for k, (_zt, _n, _u, dec, *_r) in CLIMATE.items():
            n += ctx.sql(f"khí hậu {k}", f"""
                INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size)
                SELECT 'uk', a.id, %s, %s, round((sum(f.pop * f.c_{k}) / sum(f.pop))::numeric, {dec + 1}), count(*)
                FROM hz_clim f JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='lsoa' AND a.code = f.lsoa21_code
                WHERE f.c_{k} IS NOT NULL AND left(f.lsoa21_code, 1) IN ('E', 'W') GROUP BY a.id HAVING sum(f.pop) > 0""",
                         (f"uk.climate.{k}", period))
        return {"values": n, "england_share_pct": {k: round(v, 2) for k, v in eng.items()},
                "wales_share_pct": {k: round(v, 2) for k, v in wal.items()}, "cornwall_radon_pct": round(cw, 1),
                "climate_england": {k: round(v, 1) for k, (v, _m) in clim.items()}}
