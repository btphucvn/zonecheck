"""DfT STATS19 (5 năm gần nhất) → mkt_uk.road_collision (điểm, GB) + uk.road.* theo LSOA (E&W).

Tỉ lệ theo dân cư trú dễ thổi phồng ở trung tâm thành phố (nhiều người qua lại, ít người ở), nên ngoài tỉ lệ
/1.000 dân còn lưu số vụ tuyệt đối mỗi năm (sample_size) để trang báo cáo hiển thị kèm.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date

from .base import LoadContext, LoadError, Loader
from .metrics import register_metric

log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.road_collision (
    collision_index text PRIMARY KEY,
    year smallint NOT NULL,
    occurred_on date,
    severity smallint NOT NULL,
    casualties smallint,
    vehicles smallint,
    pedestrian_casualties smallint,
    cyclist_casualties smallint,
    lsoa21_code text,
    geom geometry(Point, 4326),
    release_id bigint REFERENCES ops.dataset_release (id)
);
CREATE INDEX IF NOT EXISTS road_collision_geom ON mkt_uk.road_collision USING gist (geom);
CREATE INDEX IF NOT EXISTS road_collision_lsoa ON mkt_uk.road_collision (lsoa21_code);
COMMENT ON TABLE mkt_uk.road_collision IS 'DfT STATS19: va chạm giao thông có thương vong được cảnh sát ghi nhận, 5 năm gần nhất (GB).';
COMMENT ON COLUMN mkt_uk.road_collision.severity IS '1 = tử vong, 2 = nghiêm trọng, 3 = nhẹ (mức nặng nhất của vụ)'"""


class Stats19Loader(Loader):
    source = "dft_stats19"
    depends_on = ("boundaries_lsoa21", "census2021")
    description = "DfT STATS19 5 năm → mkt_uk.road_collision + uk.road.{collisions,ksi,vulnerable}_per_1k theo LSOA"

    def load(self, ctx: LoadContext) -> dict:
        col_f = ctx.file(r"collision-last-5-years\.csv$")
        cas_f = ctx.file(r"casualty-last-5-years\.csv$")
        with open(col_f, encoding="utf-8-sig") as f:
            header = next(csv.reader(f))
        lsoa_col = next((h for h in header if re.match(r"lsoa_of_(accident|collision)_location", h)), None)
        need = ["collision_index", "collision_year", "longitude", "latitude", "collision_severity",
                "number_of_vehicles", "number_of_casualties", "date"]
        missing = [c for c in need if c not in header] + ([] if lsoa_col else ["lsoa_of_*_location"])
        if missing:
            raise LoadError(f"STATS19 collision thiếu cột {missing}; có {header}")
        raw = ctx.stage_table("s19_col", header)
        with open(col_f, "rb") as f:
            n_raw = ctx.copy_csv(raw, f, columns=header, label="COPY collision")
        if not 300_000 <= n_raw <= 700_000:
            raise LoadError(f"Số vụ 5 năm bất thường: {n_raw:,} (GB ~100 nghìn/năm)")
        with open(cas_f, encoding="utf-8-sig") as f:
            cheader = next(csv.reader(f))
        craw = ctx.stage_table("s19_cas", cheader)
        with open(cas_f, "rb") as f:
            ctx.copy_csv(craw, f, columns=cheader, label="COPY casualty")

        for stmt in DDL.split(";\n"):
            ctx.conn.execute(stmt)
        ctx.sql("TRUNCATE road_collision", "TRUNCATE mkt_uk.road_collision")
        n = ctx.sql("INSERT road_collision", f"""
            INSERT INTO mkt_uk.road_collision (collision_index, year, occurred_on, severity, casualties, vehicles,
                pedestrian_casualties, cyclist_casualties, lsoa21_code, geom, release_id)
            SELECT c.collision_index, c.collision_year::smallint, to_date(nullif(c.date, ''), 'DD/MM/YYYY'),
                   c.collision_severity::smallint, nullif(c.number_of_casualties, '')::smallint,
                   nullif(c.number_of_vehicles, '')::smallint,
                   coalesce(k.ped, 0), coalesce(k.cyc, 0),
                   nullif(nullif(c."{lsoa_col}", '-1'), ''),
                   CASE WHEN c.longitude ~ '^-?[0-9.]+$' AND c.latitude ~ '^-?[0-9.]+$'
                        THEN ST_SetSRID(ST_MakePoint(c.longitude::float8, c.latitude::float8), 4326) END,
                   %s
            FROM {raw} c
            LEFT JOIN (SELECT collision_index, count(*) FILTER (WHERE casualty_class = '3') ped,
                              count(*) FILTER (WHERE casualty_type = '1') cyc
                       FROM {craw} GROUP BY 1) k USING (collision_index)""", (ctx.release_id,))
        ctx.expect("vụ đã nạp", n, n_raw)
        ctx.check_values_in("mức độ", "mkt_uk.road_collision", "severity", [1, 2, 3])
        ctx.check_not_null_ratio("toạ độ", "mkt_uk.road_collision", "geom", 0.99)
        ctx.check_not_null_ratio("LSOA (E&W)", "mkt_uk.road_collision", "lsoa21_code", 0.85)
        fatal = ctx.scalar("SELECT 100.0 * count(*) FILTER (WHERE severity = 1) / count(*) FROM mkt_uk.road_collision")
        if not 0.5 <= fatal <= 3:  # ~1,4% vụ có người chết
            raise LoadError(f"Tỉ lệ vụ tử vong bất thường: {fatal:.2f}%")
        years = ctx.scalar("SELECT count(DISTINCT year) FROM mkt_uk.road_collision")
        yr_max = ctx.scalar("SELECT max(year) FROM mkt_uk.road_collision")
        far = ctx.scalar("""SELECT count(*) FROM mkt_uk.road_collision r JOIN core.geo_area a
                ON a.market_code='uk' AND a.level_code='lsoa' AND a.code = r.lsoa21_code
            WHERE r.collision_index LIKE '%%0' AND NOT ST_DWithin(a.geom::geography, r.geom::geography, 2000)""")
        log.info("    %s năm (tới %s), %.2f%% vụ tử vong, mẫu: %s vụ cách LSOA > 2 km", years, yr_max, fatal, far)
        if far > n * 0.1 * 0.01:  # mẫu 1/10, cho phép 1% lệch
            raise LoadError(f"{far} vụ (mẫu) nằm xa LSOA ghi trong dữ liệu > 2 km")
        ctx.conn.execute("ANALYZE mkt_uk.road_collision")

        period = date(int(yr_max), 12, 31)
        defs = {
            "collisions_per_1k": ("Road collisions with casualties per year per 1,000 residents", "true", True),
            "ksi_per_1k": ("Fatal or serious road collisions per year per 1,000 residents", "r.severity <= 2", False),
            "vulnerable_per_1k": ("Collisions injuring pedestrians or cyclists per year per 1,000 residents",
                                  "(r.pedestrian_casualties + r.cyclist_casualties) > 0", False),
        }
        for k, (name, _, scorable) in defs.items():
            register_metric(ctx, f"uk.road.{k}", category="safety", dataset="uk.dft.stats19", value_type="rate",
                            unit="per 1,000", decimals=2, direction=-1, period_type="year", native_level="lsoa",
                            aggregation="weighted_mean", scope="uk.ew", name=name, scorable=scorable,
                            description=f"DfT STATS19, average of {years} years to {yr_max}, by collision location (LSOA); "
                                        "sample_size = collisions per year")
        ids = [f"uk.road.{k}" for k in defs]
        ctx.sql("xoá giá trị cũ", "DELETE FROM core.metric_value WHERE market_code='uk' AND metric_id = ANY(%s)", (ids,))
        total = 0
        for k, (_, cond, _) in defs.items():
            total += ctx.sql(f"uk.road.{k}", f"""
                INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size, release_id)
                SELECT 'uk', a.id, %s, %s, round((1000.0 * coalesce(c.n, 0) / {years} / pop.value_num)::numeric, 3),
                       round(coalesce(c.n, 0)::numeric / {years}), %s
                FROM core.geo_area a
                JOIN core.metric_value pop ON pop.market_code='uk' AND pop.area_id = a.id AND pop.metric_id = 'uk.census21.ts001'
                LEFT JOIN (SELECT r.lsoa21_code, count(*) n FROM mkt_uk.road_collision r WHERE {cond} GROUP BY 1) c
                       ON c.lsoa21_code = a.code
                WHERE a.market_code='uk' AND a.level_code='lsoa' AND pop.value_num > 0""",
                             (f"uk.road.{k}", period, ctx.release_id))
        n_lsoa = ctx.scalar("SELECT count(*) FROM core.geo_area WHERE market_code='uk' AND level_code='lsoa'")
        ctx.expect("giá trị LSOA", total, 3 * n_lsoa, tolerance=0.01)
        ctx.drop_stage("s19_col", "s19_cas")
        return {"collisions": n, "years": years, "fatal_pct": round(fatal, 2)}
