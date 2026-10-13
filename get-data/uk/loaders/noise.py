"""Defra Strategic Noise Round 4 (lưới dB 20 m) → mức ồn tại tâm từng postcode England → % dân theo LSOA.

Mỗi postcode lấy giá trị của ô 20 m chứa tâm postcode (không lấy max lân cận: tâm postcode hay nằm sát mặt đường, lấy max
±20 m làm ~80% dân "≥ 55 dB"). 0 = dưới ngưỡng mô hình (~40 dB). Đây là mức ồn mô hình ngoài trời tại điểm đại diện của
postcode, không phải mức ở mặt tiền từng nhà như số liệu phơi nhiễm chính thức của Defra.
"""
from __future__ import annotations

import itertools
import logging
import re
from datetime import date

from .base import LoadContext, LoadError, Loader
from .metrics import register_metric

log = logging.getLogger(__name__)

LAYERS = ["road_lden", "road_lnight", "rail_lden", "rail_lnight", "airport_lden", "airport_lnight"]
TILE_M = 10_000

DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.postcode_noise (
    postcode text PRIMARY KEY REFERENCES mkt_uk.postcode (postcode),
    road_lden smallint, road_lnight smallint, rail_lden smallint, rail_lnight smallint,
    airport_lden smallint, airport_lnight smallint,
    release_id bigint REFERENCES ops.dataset_release (id)
);
COMMENT ON TABLE mkt_uk.postcode_noise IS 'Mức ồn (dB, làm tròn) tại tâm postcode England theo Defra Strategic Noise Mapping Round 4 (2022), ô lưới 20 m chứa tâm postcode. 0 = dưới ngưỡng mô hình (~40 dB).';
COMMENT ON COLUMN mkt_uk.postcode_noise.road_lden IS 'Đường bộ, Lden (trung bình 24 giờ có phạt tối/đêm), dB';
COMMENT ON COLUMN mkt_uk.postcode_noise.road_lnight IS 'Đường bộ, Lnight (23:00–07:00), dB'"""

# metric key → (tên, biểu thức điều kiện trên bảng postcode_noise n, scorable)
METRICS = {
    "road_lden55": ("Residents exposed to road noise of 55 dB Lden or more", "n.road_lden >= 55", False),
    "road_lden65": ("Residents exposed to high road noise (65 dB Lden or more)", "n.road_lden >= 65", True),
    "rail_lden55": ("Residents exposed to rail noise of 55 dB Lden or more", "n.rail_lden >= 55", False),
    "airport_lden50": ("Residents exposed to aircraft noise of 50 dB Lden or more", "n.airport_lden >= 50", False),
    "any_lden55": ("Residents exposed to transport noise of 55 dB Lden or more (road, rail or aircraft)",
                   "greatest(n.road_lden, n.rail_lden, n.airport_lden) >= 55", False),
    "night50": ("Residents exposed to night-time transport noise of 50 dB Lnight or more",
                "greatest(n.road_lnight, n.rail_lnight, n.airport_lnight) >= 50", False),
}


class NoiseLoader(Loader):
    source = "defra_noise"
    depends_on = ("onspd", "boundaries_lsoa21", "census2021")
    description = "Defra noise Round 4 → mkt_uk.postcode_noise + uk.noise.*_share theo LSOA (England)"

    def load(self, ctx: LoadContext) -> dict:
        import numpy as np
        import psycopg
        from PIL import Image

        from common.config import database_url

        tiles = {}
        for p in ctx.files(r"^[a-z]+_l(den|night)_\d{3}_\d{3}\.png$"):
            m = re.match(r"^([a-z]+_l(?:den|night))_(\d{3})_(\d{3})\.png$", p.name)
            tiles.setdefault((int(m.group(2)), int(m.group(3))), {})[m.group(1)] = p
        n_road = sum(1 for t in tiles.values() if "road_lden" in t)
        if n_road < 1000:
            raise LoadError(f"Chỉ có {n_road} ô road_lden (kỳ vọng ~1.400)")
        for stmt in DDL.split(";\n"):
            ctx.conn.execute(stmt)
        ctx.sql("TRUNCATE postcode_noise", "TRUNCATE mkt_uk.postcode_noise")

        def read(path):
            a = np.asarray(Image.open(path))
            pgw = [float(x) for x in path.with_suffix(".pgw").read_text().split()]
            return a, pgw  # pgw: sx, 0, 0, -sy, x tâm pixel trái-trên, y tâm pixel trái-trên

        rconn = psycopg.connect(database_url())
        cur = rconn.cursor(name="pcs")
        cur.itersize = 50_000
        cur.execute(f"""
            SELECT postcode, x, y, floor(x / {TILE_M})::int, floor(y / {TILE_M})::int
            FROM (SELECT postcode, ST_X(g) x, ST_Y(g) y FROM (
                    SELECT postcode, ST_Transform(geom, 27700) g FROM mkt_uk.postcode
                    WHERE country_code = 'E92000001' AND status = 'live' AND geom IS NOT NULL) a) b
            ORDER BY 4, 5""")

        def rows():
            for (tx, ty), grp in itertools.groupby(cur, key=lambda r: (r[3], r[4])):
                pcs = list(grp)
                vals = {}
                for layer in LAYERS:
                    path = tiles.get((tx, ty), {}).get(layer)
                    if path is None:
                        vals[layer] = [0] * len(pcs)
                        continue
                    a, (sx, _, _, nsy, x0, y0) = read(path)
                    h, w = a.shape
                    dil = a
                    xs = np.array([p[1] for p in pcs])
                    ys = np.array([p[2] for p in pcs])
                    col = np.rint((xs - x0) / sx).astype(int)
                    row = np.rint((ys - y0) / nsy).astype(int)
                    inside = (col >= 0) & (col < w) & (row >= 0) & (row < h)
                    v = np.zeros(len(pcs), dtype=int)
                    v[inside] = dil[row[inside], col[inside]]
                    vals[layer] = v.tolist()
                for i, p in enumerate(pcs):
                    yield (p[0], *[vals[layer][i] for layer in LAYERS], ctx.release_id)
        try:
            n = ctx.copy_rows("mkt_uk.postcode_noise", ["postcode", *LAYERS, "release_id"], rows(),
                              "lấy mẫu mức ồn tại postcode")
        finally:
            cur.close()
            rconn.close()
        n_pc = ctx.scalar("SELECT count(*) FROM mkt_uk.postcode WHERE country_code='E92000001' AND status='live' AND geom IS NOT NULL")
        ctx.expect("postcode England đã lấy mẫu", n, n_pc)
        ctx.check_range("road_lden", "mkt_uk.postcode_noise", "nullif(road_lden, 0)", 35, 100)
        ctx.conn.execute("ANALYZE mkt_uk.postcode_noise")

        ctx.sql("dân theo postcode", """
            CREATE TEMP TABLE pcs ON COMMIT DROP AS
            SELECT p.postcode, p.lsoa21_code, v.value_num / count(*) OVER (PARTITION BY p.oa21_code) AS pop
            FROM mkt_uk.postcode p
            JOIN core.geo_area oa ON oa.market_code='uk' AND oa.level_code='oa' AND oa.code = p.oa21_code
            JOIN core.metric_value v ON v.market_code='uk' AND v.area_id = oa.id AND v.metric_id='uk.census21.ts001'
            WHERE p.status='live' AND p.geom IS NOT NULL AND p.country_code='E92000001'""")
        flags = ", ".join(f"({cond}) AS f_{k}" for k, (_, cond, _) in METRICS.items())
        ctx.sql("postcode × ngưỡng ồn", f"""
            CREATE TEMP TABLE pcn ON COMMIT DROP AS
            SELECT p.lsoa21_code, p.pop, {flags}
            FROM pcs p JOIN mkt_uk.postcode_noise n USING (postcode)""")
        eng = dict(ctx.conn.execute(f"""SELECT k, 100.0 * sum(pop) FILTER (WHERE f) / sum(pop) FROM pcn
            CROSS JOIN LATERAL (VALUES {", ".join(f"('{k}', f_{k})" for k in METRICS)}) m(k, f) GROUP BY k""").fetchall())
        log.info("    %% dân England: %s", {k: round(v, 1) for k, v in eng.items()})
        # Defra Round 4: khoảng 10 triệu người (≈ 18%) ở mức ồn đường bộ ≥ 55 dB Lden; đường sắt, sân bay ít hơn nhiều
        if not (5 <= eng["road_lden55"] <= 75 and eng["road_lden65"] < eng["road_lden55"] / 2
                and eng["rail_lden55"] < eng["road_lden55"] and eng["airport_lden50"] < 15
                and eng["any_lden55"] >= eng["road_lden55"]):
            raise LoadError(f"Tỉ lệ dân bị ồn bất thường: {eng}")
        # đối chiếu chéo: Hounslow (sát Heathrow) phải có tỉ lệ ồn máy bay cao hơn hẳn trung bình England
        houn = ctx.scalar("""SELECT 100.0 * sum(pop) FILTER (WHERE f_airport_lden50) / sum(pop) FROM pcn
            WHERE lsoa21_code IN (SELECT lsoa21_code FROM mkt_uk.postcode WHERE lad_code = 'E09000018')""")
        log.info("    Hounslow (Heathrow): %.1f%% dân ≥ 50 dB Lden máy bay", houn or 0)
        if houn is None or houn < 3 * max(eng["airport_lden50"], 0.5):
            raise LoadError(f"Kiểm tra định hướng thất bại: Hounslow {houn} không cao hơn England {eng['airport_lden50']:.1f}%")

        # đối chiếu định hướng: Westminster (trung tâm London) ồn hơn hẳn Westmorland and Furness (nông thôn)
        urb, rur = [ctx.scalar("""SELECT 100.0 * sum(pop) FILTER (WHERE f_road_lden55) / sum(pop) FROM pcn
            WHERE lsoa21_code IN (SELECT lsoa21_code FROM mkt_uk.postcode WHERE lad_code = %s)""", (lad,))
                    for lad in ("E09000033", "E06000064")]
        log.info("    road ≥ 55 dB: Westminster %.1f%%, Westmorland and Furness %.1f%%", urb or 0, rur or 0)
        if urb is None or rur is None or urb < rur + 10:
            raise LoadError(f"Kiểm tra định hướng thành thị/nông thôn thất bại: Westminster {urb}, Westmorland and Furness {rur}")

        period = date(2022, 1, 1)
        for k, (name, _, scorable) in METRICS.items():
            register_metric(ctx, f"uk.noise.{k}_share", category="environment", dataset="uk.defra.noise_r4",
                            value_type="percent", unit="%", decimals=1, direction=-1, period_type="snapshot",
                            native_level="lsoa", aggregation="weighted_mean", scope="uk.england", name=name,
                            scorable=scorable,
                            description="Defra Strategic Noise Mapping Round 4 (2022), modelled level at each postcode "
                                        "centre (highest within 20 m), weighted by residents")
        ids = [f"uk.noise.{k}_share" for k in METRICS]
        ctx.sql("xoá giá trị cũ", "DELETE FROM core.metric_value WHERE market_code='uk' AND metric_id = ANY(%s)", (ids,))
        ins = ctx.sql("tỉ lệ dân theo LSOA", f"""
            INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size, release_id)
            SELECT 'uk', a.id, 'uk.noise.' || m.k || '_share', %s,
                   round((100.0 * coalesce(sum(z.pop) FILTER (WHERE m.f), 0) / sum(z.pop))::numeric, 2), count(*), %s
            FROM pcn z JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='lsoa' AND a.code = z.lsoa21_code
            CROSS JOIN LATERAL (VALUES {", ".join(f"('{k}', z.f_{k})" for k in METRICS)}) m(k, f)
            GROUP BY a.id, m.k HAVING sum(z.pop) > 0""", (period, ctx.release_id))
        n_lsoa = ctx.scalar("SELECT count(*) FROM core.geo_area WHERE market_code='uk' AND level_code='lsoa' AND code LIKE 'E%'")
        ctx.expect("giá trị LSOA", ins, len(METRICS) * n_lsoa, tolerance=0.01)
        return {"postcodes": n, "england_share_pct": {k: round(v, 2) for k, v in eng.items()},
                "hounslow_airport_pct": round(houn, 1)}
