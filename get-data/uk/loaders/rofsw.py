"""OS Open UPRN → toạ độ nhà (UPRN có EPC) và EA RoFSW (lũ nước mặt) → % nhà có rủi ro theo LSOA.

Lũ nước mặt rất cục bộ (theo từng con phố), nên tâm postcode không đủ chính xác. Thay vào đó lấy mẫu
lưới lớp rủi ro 5 m đúng tại toạ độ UPRN của từng nhà. Đã thử lấy mức cao nhất trong ±5 m: tỉ lệ nhà có rủi ro
tăng gấp đôi (Leeds 11% → 22%, England ~25%), xa số EA công bố (~15% cơ sở). Lấy đúng tại điểm thì sát hơn.
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import date

from .base import STAGE, LoadContext, LoadError, Loader, zip_members
from .metrics import register_metric

log = logging.getLogger(__name__)

UPRN_DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.uprn_point (
    uprn bigint PRIMARY KEY,
    x real NOT NULL,
    y real NOT NULL,
    geom geometry(Point, 4326) NOT NULL,
    release_id bigint REFERENCES ops.dataset_release (id)
);
COMMENT ON TABLE mkt_uk.uprn_point IS 'Toạ độ OS Open UPRN (OGL) cho các UPRN đang dùng: nhà có EPC. Dùng cho chỉ số theo từng nhà (lũ nước mặt...).';
COMMENT ON COLUMN mkt_uk.uprn_point.x IS 'Easting EPSG:27700 (m).';
COMMENT ON COLUMN mkt_uk.uprn_point.y IS 'Northing EPSG:27700 (m).'"""


class OpenUprnLoader(Loader):
    source = "os_open_uprn"
    depends_on = ("epc",)
    description = "OS Open UPRN → mkt_uk.uprn_point (chỉ UPRN của nhà có EPC, thay toàn bộ)"

    def load(self, ctx: LoadContext) -> dict:
        z = ctx.file(r"\.zip$")
        members = zip_members(z, r"osopenuprn_\d+\.csv$")
        if len(members) != 1:
            raise LoadError(f"Cần đúng 1 file osopenuprn_*.csv trong {z.name}, thấy {members}")
        cols = ["uprn", "x", "y", "lat", "lon"]
        raw = ctx.stage_table("uprn_raw", cols, {"uprn": "bigint", "x": "float8", "y": "float8", "lat": "float8", "lon": "float8"})
        with zipfile.ZipFile(z) as zf, zf.open(members[0]) as f:
            header = f.readline().decode("utf-8-sig").strip()
            if header != "UPRN,X_COORDINATE,Y_COORDINATE,LATITUDE,LONGITUDE":
                raise LoadError(f"Header Open UPRN đổi: {header!r}")
            n = ctx.copy_csv(raw, io.BufferedReader(f), columns=cols, header=False, label=f"COPY {members[0]}",
                             analyze=False)
        if not 38_000_000 <= n <= 46_000_000:
            raise LoadError(f"Số UPRN bất thường: {n:,} (GB ~41 triệu)")
        ctx.check_range("easting", raw, "x", 0, 700_000)
        ctx.check_range("northing", raw, "y", 0, 1_300_000)
        for stmt in UPRN_DDL.split(";\n"):
            ctx.conn.execute(stmt)
        ctx.sql("TRUNCATE uprn_point", "TRUNCATE mkt_uk.uprn_point")
        ctx.conn.execute("ALTER TABLE mkt_uk.uprn_point DROP CONSTRAINT IF EXISTS uprn_point_pkey")
        ins = ctx.sql("INSERT uprn_point (nhà có EPC)", f"""
            INSERT INTO mkt_uk.uprn_point (uprn, x, y, geom, release_id)
            SELECT r.uprn, r.x, r.y, ST_SetSRID(ST_MakePoint(r.lon, r.lat), 4326), %s
            FROM {raw} r WHERE r.uprn IN (SELECT uprn FROM mkt_uk.epc_certificate WHERE uprn IS NOT NULL)""",
                      (ctx.release_id,))
        ctx.sql("khoá chính", "ALTER TABLE mkt_uk.uprn_point ADD CONSTRAINT uprn_point_pkey PRIMARY KEY (uprn)")
        epc_uprns = ctx.scalar("SELECT count(DISTINCT uprn) FROM mkt_uk.epc_certificate WHERE uprn IS NOT NULL")
        rate = ins / epc_uprns
        log.info("    %s/%s UPRN của EPC có toạ độ (%.1f%%)", f"{ins:,}", f"{epc_uprns:,}", rate * 100)
        if rate < 0.95:  # UPRN đã khai tử/ảo trong EPC không có trong Open UPRN
            raise LoadError(f"Chỉ {rate:.1%} UPRN của EPC có trong Open UPRN")
        # đối chiếu chéo: toạ độ nhà phải gần tâm postcode của EPC (lệch > 5 km = ghép sai)
        far = ctx.scalar("""SELECT count(*) FROM (SELECT DISTINCT ON (e.uprn) u.geom, p.geom pg
                FROM mkt_uk.epc_certificate e JOIN mkt_uk.uprn_point u USING (uprn) JOIN mkt_uk.postcode p USING (postcode)
                WHERE e.is_latest_for_address AND e.uprn % 50 = 0) s
            WHERE NOT ST_DWithin(geom::geography, pg::geography, 5000)""")
        sample = ctx.scalar("SELECT count(*) FROM mkt_uk.uprn_point WHERE uprn % 50 = 0")
        log.info("    mẫu 1/50: %s/%s nhà cách tâm postcode > 5 km", far, sample)
        if far > sample * 0.005:
            raise LoadError(f"{far}/{sample} nhà (mẫu) cách tâm postcode > 5 km")
        ctx.conn.execute("ANALYZE mkt_uk.uprn_point")
        ctx.drop_stage("uprn_raw")
        ctx.expect("mkt_uk.uprn_point", ins, ins)
        return {"uprn_gb": n, "homes_with_point": ins, "epc_uprn_coverage": round(rate, 4)}


METRICS = {
    "sw_high": ("Homes at high risk of surface water flooding (3.3%+ a year)", 3, -1, True),
    "sw_medium_plus": ("Homes at medium or high risk of surface water flooding (1%+ a year)", 2, -1, False),
    "sw_any": ("Homes at any risk of surface water flooding (0.1%+ a year)", 1, -1, False),
}


def write_sw_metrics(ctx: LoadContext, res: str, country: str, period, dataset: str, description: str) -> int:
    """stage(uprn, lsoa, sev) → uk.zone.sw_*_share theo LSOA của một nước (E/W). Chỉ thay giá trị LSOA của nước đó."""
    for key, (name, _, direction, scorable) in METRICS.items():
        # England (EA NaFRA2) + Wales (NRW): cùng thang High/Medium/Low → một chỉ số E&W
        register_metric(ctx, f"uk.zone.{key}_share", category="risk", dataset="uk.ea.rofsw", value_type="percent",
                        unit="%", decimals=1, direction=direction, period_type="snapshot", native_level="lsoa",
                        aggregation="weighted_mean", scope="uk.ew", name=name, scorable=scorable,
                        description="Surface water flood risk sampled at each home with an EPC (band at the OS Open "
                                    "UPRN location). England: EA NaFRA2 RoFSW; Wales: NRW Flood Risk from Surface Water")
    ids = [f"uk.zone.{k}_share" for k in METRICS]
    ctx.sql(f"xoá giá trị cũ ({country})", """DELETE FROM core.metric_value v USING core.geo_area a
        WHERE a.id = v.area_id AND a.level_code = 'lsoa' AND a.code LIKE %s AND v.market_code='uk' AND v.metric_id = ANY(%s)""",
            (country + "%", ids))
    ins = ctx.sql(f"tỉ lệ nhà theo LSOA ({country}, {dataset})", f"""
        INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size, release_id)
        SELECT 'uk', a.id, 'uk.zone.' || v.k || '_share', %s,
               round(100.0 * count(*) FILTER (WHERE r.sev >= v.m) / count(*), 2), count(*), %s
        FROM {res} r JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='lsoa' AND a.code = r.lsoa
        CROSS JOIN (VALUES ('sw_high', 3), ('sw_medium_plus', 2), ('sw_any', 1)) v(k, m)
        GROUP BY a.id, v.k""", (period, ctx.release_id))
    n_lsoa = ctx.scalar("SELECT count(*) FROM core.geo_area WHERE market_code='uk' AND level_code='lsoa' AND code LIKE %s",
                        (country + "%",))
    ctx.expect(f"giá trị LSOA (3 chỉ số × LSOA {country})", ins, 3 * n_lsoa, tolerance=0.01)
    return ins


class RofswLoader(Loader):
    source = "ea_rofsw"
    depends_on = ("os_open_uprn", "epc", "onspd", "boundaries_lsoa21")
    description = "EA RoFSW 5 m × toạ độ nhà → uk.zone.sw_{high,medium_plus,any}_share theo LSOA (England)"

    def load(self, ctx: LoadContext) -> dict:
        import numpy as np
        from PIL import Image

        from ..sources.rofsw import RES_M, TILE_M, tile_name
        period = date.fromisoformat(ctx.version)
        tiles = {p.name for p in ctx.files(r"^rofsw_\d{3}_\d{3}\.png$")}
        if len(tiles) < 500:
            raise LoadError(f"Chỉ có {len(tiles)} ô RoFSW")
        res = ctx.stage_table("rofsw_home", ["uprn", "lsoa", "sev"], {"uprn": "bigint", "sev": "smallint"})

        import itertools

        import psycopg

        from common.config import database_url
        n_homes = ctx.scalar("""SELECT count(DISTINCT e.uprn) FROM mkt_uk.epc_certificate e
            JOIN mkt_uk.uprn_point u USING (uprn) JOIN mkt_uk.postcode p ON p.postcode = e.postcode
            WHERE e.is_latest_for_address AND p.lsoa21_code LIKE 'E%'""")
        log.info("    %s nhà England có toạ độ", f"{n_homes:,}")
        # kết nối đọc riêng + server-side cursor sắp theo ô: không nạp 20+ triệu nhà vào RAM, và không FETCH
        # trên cùng kết nối đang COPY
        rconn = psycopg.connect(database_url())
        cur = rconn.cursor(name="homes")
        cur.itersize = 100_000
        cur.execute(f"""
            SELECT uprn, lsoa, x, y, floor(x / {TILE_M})::int AS tx, floor(y / {TILE_M})::int AS ty
            FROM (SELECT DISTINCT ON (u.uprn) u.uprn, p.lsoa21_code AS lsoa, u.x, u.y
                  FROM mkt_uk.epc_certificate e JOIN mkt_uk.uprn_point u USING (uprn)
                  JOIN mkt_uk.postcode p ON p.postcode = e.postcode
                  WHERE e.is_latest_for_address AND p.lsoa21_code LIKE 'E%%'
                  ORDER BY u.uprn, e.lodgement_date DESC) s
            ORDER BY tx, ty""")

        def rows():
            missing_tiles = 0
            for (tx, ty), grp in itertools.groupby(cur, key=lambda r: (r[4], r[5])):
                homes = list(grp)
                name = tile_name(tx, ty)
                if name not in tiles:  # ô không có vùng ngập nào
                    missing_tiles += 1
                    for uprn, lsoa, *_ in homes:
                        yield (uprn, lsoa, 0)
                    continue
                cls = np.asarray(Image.open(ctx.dir / name))
                sev = np.select([cls == 1, cls == 2, cls == 3], [3, 2, 1], 0).astype(np.uint8)
                h, w = sev.shape
                xs = np.array([hm[2] for hm in homes])
                ys = np.array([hm[3] for hm in homes])
                col = np.clip(((xs - tx * TILE_M) // RES_M).astype(int), 0, w - 1)
                row = np.clip((((ty + 1) * TILE_M - ys) // RES_M).astype(int), 0, h - 1)
                for (uprn, lsoa, *_), v in zip(homes, sev[row, col].tolist()):
                    yield (uprn, lsoa, v)
            log.info("    %s ô có nhà nhưng không có file rủi ro (= không có vùng ngập)", missing_tiles)
        try:
            n = ctx.copy_rows(res, ["uprn", "lsoa", "sev"], rows(), "lấy mẫu rủi ro tại từng nhà")
        finally:
            cur.close()
            rconn.close()
        ctx.expect("nhà đã lấy mẫu", n, n_homes)

        shares = dict(ctx.conn.execute(f"""SELECT k, 100.0 * count(*) FILTER (WHERE sev >= m) / count(*)
            FROM {res} CROSS JOIN (VALUES ('sw_high', 3), ('sw_medium_plus', 2), ('sw_any', 1)) v(k, m) GROUP BY k""").fetchall())
        log.info("    %% nhà England: %s", {k: round(v, 2) for k, v in shares.items()})
        # NaFRA2: ~4,6 triệu cơ sở England có rủi ro nước mặt (~15%, tính theo giao với nền nhà nên cao hơn lấy tại điểm)
        if not (5 <= shares["sw_any"] <= 25 and shares["sw_high"] < shares["sw_medium_plus"] < shares["sw_any"]
                and 0.5 <= shares["sw_high"] <= 10):
            raise LoadError(f"Tỉ lệ nhà có rủi ro nước mặt bất thường: {shares}")
        # đối chiếu: Westminster (đô thị dày, nhiều bề mặt không thấm) có tỉ lệ nhà rủi ro cao hơn Cornwall
        wm, co = (ctx.scalar(f"""SELECT 100.0 * count(*) FILTER (WHERE r.sev >= 1) / count(*) FROM {res} r
            WHERE r.lsoa IN (SELECT lsoa21_code FROM mkt_uk.postcode WHERE lad_code = %s)""", (c,))
                  for c in ("E09000033", "E06000052"))
        log.info("    nhà có rủi ro: Westminster %.1f%%, Cornwall %.1f%%", wm or 0, co or 0)
        if wm is None or co is None or wm <= co:
            raise LoadError(f"Kiểm tra định hướng thất bại: Westminster {wm} không cao hơn Cornwall {co}")
        ins = write_sw_metrics(ctx, res, "E", period, "uk.ea.rofsw",
                               "EA Risk of Flooding from Surface Water (NaFRA2), sampled at each home with an EPC "
                               "(band at the OS Open UPRN location)")
        ctx.drop_stage("rofsw_home")
        return {"homes": n, "england_share_pct": {k: round(v, 2) for k, v in shares.items()}, "westminster_any_pct": round(wm, 1), "cornwall_any_pct": round(co, 1)}


class NrwRofswLoader(Loader):
    """Wales: polygon NRW (theo ô 10 km, EPSG:27700) × toạ độ nhà → cùng chỉ số uk.zone.sw_*_share cho LSOA Wales.

    Nhẹ RAM: mỗi lần chỉ dựng STRtree cho một ô (tối đa vài chục nghìn polygon) và các nhà trong ô đó.

    Polygon NRW (lưới 2 m) chừa đúng khuôn toà nhà, nên lấy đúng tại toạ độ UPRN (giữa nhà) chỉ ra ~1% nhà có rủi ro.
    Vì vậy tính nhà có rủi ro khi vùng ngập nằm trong SW_RADIUS_M quanh toạ độ (≈ nửa bề rộng một căn nhà), tương
    đương England lấy mẫu trên lưới 5 m. Thử mẫu 5 ô: 0 m → 0–2,5%, 3 m → 1–9%, 5 m → 3–14%, 8 m → 5–21%.
    """

    SW_RADIUS_M = 5

    source = "nrw_rofsw"
    depends_on = ("os_open_uprn", "epc", "onspd", "boundaries_lsoa21")
    description = "NRW lũ nước mặt (Wales) × toạ độ nhà → uk.zone.sw_{high,medium_plus,any}_share theo LSOA Wales"

    def load(self, ctx: LoadContext) -> dict:
        import gzip
        import itertools
        import json

        import numpy as np
        import shapely

        from ..sources.rofsw import TILE_M, nrw_tile_name
        period = date.fromisoformat(ctx.version)
        tiles = {p.name for p in ctx.files(r"^nrw_sw_\d{3}_\d{3}\.json\.gz$")}
        if len(tiles) < 100:
            raise LoadError(f"Chỉ có {len(tiles)} ô NRW")
        res = ctx.stage_table("nrw_sw_home", ["uprn", "lsoa", "sev"], {"uprn": "bigint", "sev": "smallint"})
        n_homes = ctx.scalar("""SELECT count(DISTINCT e.uprn) FROM mkt_uk.epc_certificate e
            JOIN mkt_uk.uprn_point u USING (uprn) JOIN mkt_uk.postcode p ON p.postcode = e.postcode
            WHERE e.is_latest_for_address AND p.lsoa21_code LIKE 'W%'""")
        log.info("    %s nhà Wales có toạ độ", f"{n_homes:,}")
        # đọc hết nhà Wales (~1 triệu dòng) rồi tính offline: lần trước COPY mở suốt 10 phút tính toán qua tunnel bị đứt
        homes_all = ctx.conn.execute(f"""
            SELECT uprn, lsoa, x, y, floor(x / {TILE_M})::int AS tx, floor(y / {TILE_M})::int AS ty
            FROM (SELECT DISTINCT ON (u.uprn) u.uprn, p.lsoa21_code AS lsoa, u.x, u.y
                  FROM mkt_uk.epc_certificate e JOIN mkt_uk.uprn_point u USING (uprn)
                  JOIN mkt_uk.postcode p ON p.postcode = e.postcode
                  WHERE e.is_latest_for_address AND p.lsoa21_code LIKE 'W%%'
                  ORDER BY u.uprn, e.lodgement_date DESC) s
            ORDER BY tx, ty""").fetchall()
        tstats = {"tiles_with_homes": 0, "tiles_without_file": 0, "polygons": 0}
        out_rows = []
        for (tx, ty), grp in itertools.groupby(homes_all, key=lambda r: (r[4], r[5])):
            homes = list(grp)
            tstats["tiles_with_homes"] += 1
            name = nrw_tile_name(tx, ty)
            if name not in tiles:  # ô không có vùng rủi ro
                tstats["tiles_without_file"] += 1
                out_rows += [(uprn, lsoa, 0) for uprn, lsoa, *_ in homes]
                continue
            with gzip.open(ctx.dir / name, "rt") as f:
                feats = json.load(f)
            tstats["polygons"] += len(feats)
            sev_of = np.array([ft[0] for ft in feats], dtype=np.int8)
            polys = shapely.make_valid(np.array([shapely.Polygon(ft[1][0], ft[1][1:]) for ft in feats], dtype=object))
            tree = shapely.STRtree(polys)
            pts = shapely.points(np.array([[h[2], h[3]] for h in homes], dtype=float))
            hi, pi = tree.query(pts, predicate="dwithin", distance=self.SW_RADIUS_M)
            sev = np.zeros(len(homes), dtype=np.int8)
            np.maximum.at(sev, hi, sev_of[pi])
            out_rows += [(uprn, lsoa, v) for (uprn, lsoa, *_), v in zip(homes, sev.tolist())]
            if tstats["tiles_with_homes"] % 50 == 0:
                log.info("    %s ô đã xử lý", tstats["tiles_with_homes"])
        del homes_all
        n = ctx.copy_rows(res, ["uprn", "lsoa", "sev"], out_rows, "COPY rủi ro tại từng nhà (Wales)")
        log.info("    ô: %s", tstats)
        ctx.expect("nhà đã lấy mẫu", n, n_homes)
        shares = dict(ctx.conn.execute(f"""SELECT k, 100.0 * count(*) FILTER (WHERE sev >= m) / count(*)
            FROM {res} CROSS JOIN (VALUES ('sw_high', 3), ('sw_medium_plus', 2), ('sw_any', 1)) v(k, m) GROUP BY k""").fetchall())
        log.info("    %% nhà Wales: %s", {k: round(v, 2) for k, v in shares.items()})
        # NRW ước tính ~1/9–1/8 cơ sở Wales có rủi ro nước mặt & suối nhỏ; England (cùng cách lấy mẫu) ~10%
        if not (5 <= shares["sw_any"] <= 15 and shares["sw_high"] < shares["sw_medium_plus"] < shares["sw_any"]):
            raise LoadError(f"Tỉ lệ nhà Wales có rủi ro nước mặt bất thường: {shares}")
        # lớp gồm cả suối nhỏ nên vùng nông thôn thung lũng (Powys) có thể cao hơn đô thị (Cardiff) — không dùng làm
        # kiểm tra định hướng. Thay vào đó: các LAD phải chênh nhau rõ (dữ liệu đồng đều = lỗi ghép/toạ độ)
        lad = ctx.conn.execute(f"""SELECT p.lad_code, 100.0 * count(*) FILTER (WHERE r.sev >= 1) / count(*)
            FROM {res} r JOIN (SELECT DISTINCT lsoa21_code, lad_code FROM mkt_uk.postcode WHERE lsoa21_code LIKE 'W%%') p
              ON p.lsoa21_code = r.lsoa GROUP BY 1""").fetchall()
        vals = sorted(float(v) for _, v in lad)
        cf = next((float(v) for c, v in lad if c == "W06000015"), None)
        pw = next((float(v) for c, v in lad if c == "W06000023"), None)
        log.info("    %s LAD: thấp nhất %.1f%%, cao nhất %.1f%%; Cardiff %.1f%%, Powys %.1f%%", len(vals), vals[0], vals[-1],
                 cf or 0, pw or 0)
        if len(vals) < 20 or vals[-1] < 1.5 * vals[0]:
            raise LoadError(f"Tỉ lệ theo LAD bất thường (quá đồng đều hoặc thiếu LAD): {vals}")
        ins = write_sw_metrics(ctx, res, "W", period, "uk.nrw.rofsw",
                               "NRW Flood Risk from Surface Water and Small Watercourses within 5 m of each home with an EPC")
        ctx.drop_stage("nrw_sw_home")
        return {"homes": n, "values": ins, "radius_m": self.SW_RADIUS_M, "wales_share_pct": {k: round(v, 2) for k, v in shares.items()},
                "cardiff_any_pct": round(cf, 1), "powys_any_pct": round(pw, 1), **tstats}
