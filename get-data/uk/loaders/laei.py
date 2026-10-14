"""LAEI 2022 (GLA, lưới 20 m) → mkt_uk.postcode_air: NO2, NOx, PM10, PM2.5 trung bình năm và số ngày PM10 > 50 µg/m³
tại từng postcode trong vùng mô hình (Greater London và vành đai). Giá trị = trung bình các ô hợp lệ trong cửa sổ
3×3 ô (60 m) quanh toạ độ postcode, để một điểm sát mép đường không quyết định cả postcode.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile

from .base import LoadContext, LoadError, Loader

log = logging.getLogger(__name__)

GRIDS = {"no2": "NO2", "nox": "NOx", "pm10": "PM10m", "pm25": "PM25", "pm10_days": "PM10d"}
DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.postcode_air (
    postcode text PRIMARY KEY,
    no2 real, nox real, pm10 real, pm25 real, pm10_days real,
    release_id bigint REFERENCES ops.dataset_release (id)
);
COMMENT ON TABLE mkt_uk.postcode_air IS 'LAEI 2022 (GLA, OGL): nồng độ trung bình năm 2022 tại postcode (cửa sổ 60 m), µg/m³; pm10_days = số ngày PM10 > 50 µg/m³.'"""


def read_asc(zf: zipfile.ZipFile, member: str):
    import numpy as np
    raw = zf.read(member)
    head, pos = {}, 0
    for _ in range(6):
        end = raw.index(b"\n", pos)
        k, v = raw[pos:end].decode().split()
        head[k.lower()] = float(v)
        pos = end + 1
    arr = np.array(raw[pos:].split(), dtype=np.float32)
    nr, nc = int(head["nrows"]), int(head["ncols"])
    if arr.size != nr * nc:
        raise LoadError(f"{member}: {arr.size} giá trị, kỳ vọng {nr}×{nc}")
    arr = arr.reshape(nr, nc)
    arr[arr == head["nodata_value"]] = np.nan
    return head, arr


class LaeiLoader(Loader):
    source = "laei"
    depends_on = ("onspd",)
    description = "LAEI 2022 lưới 20 m → mkt_uk.postcode_air (NO2, NOx, PM10, PM2.5, ngày PM10 vượt ngưỡng)"

    def load(self, ctx: LoadContext) -> dict:
        import numpy as np
        z = zipfile.ZipFile(ctx.file(r"Concentrations.*ASCII.*\.zip$"))
        names = z.namelist()
        grids, head0 = {}, None
        for k, tag in GRIDS.items():
            m = [n for n in names if re.search(rf"_{tag}\.asc$", n)]
            if len(m) != 1:
                raise LoadError(f"Không thấy lưới {tag}: {m}")
            head, arr = read_asc(z, m[0])
            if head0 and any(head[x] != head0[x] for x in ("ncols", "nrows", "xllcorner", "yllcorner", "cellsize")):
                raise LoadError(f"Lưới {tag} khác khung lưới NO2")
            head0 = head0 or head
            grids[k] = arr
            log.info("    %s: %s×%s, TB %.1f, max %.1f", tag, arr.shape[0], arr.shape[1], np.nanmean(arr), np.nanmax(arr))
        nr, nc, x0, y0, cs = int(head0["nrows"]), int(head0["ncols"]), head0["xllcorner"], head0["yllcorner"], head0["cellsize"]
        x1, y1 = x0 + nc * cs, y0 + nr * cs
        pcs = ctx.conn.execute("""
            SELECT postcode, ST_X(g), ST_Y(g) FROM (
                SELECT postcode, ST_Transform(geom, 27700) g FROM mkt_uk.postcode
                WHERE status = 'live' AND geom IS NOT NULL
                  AND geom && ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 27700), 4326)) x""", (x0, y0, x1, y1)).fetchall()
        rows = []
        for pc, x, y in pcs:
            c, r = int((x - x0) // cs), nr - 1 - int((y - y0) // cs)
            if not (1 <= c < nc - 1 and 1 <= r < nr - 1):
                continue
            vals = {k: float(np.nanmean(a[r - 1:r + 2, c - 1:c + 2])) if not np.all(np.isnan(a[r - 1:r + 2, c - 1:c + 2])) else None
                    for k, a in grids.items()}
            if vals["no2"] is None:
                continue
            rows.append((pc, *(None if v is None else round(v, 2) for v in vals.values())))
        log.info("    %s postcode có giá trị (trong %s postcode thuộc khung lưới)", f"{len(rows):,}", f"{len(pcs):,}")
        if not 150_000 <= len(rows) <= 400_000:
            raise LoadError(f"Số postcode có giá trị LAEI bất thường: {len(rows)}")
        ctx.conn.execute(DDL)
        st = ctx.stage_table("air", ["postcode", *GRIDS], {k: "float8" for k in GRIDS})
        ctx.copy_rows(st, ["postcode", *GRIDS], rows, "COPY LAEI postcode")
        ctx.check_range("NO2", st, "no2", 3, 120)
        ctx.check_range("PM2.5", st, "pm25", 3, 40)
        ctx.check_range("PM10", st, "pm10", 5, 60)
        ctx.check_range("ngày PM10 > 50", st, "pm10_days", 0, 60)
        # kiểm tra định hướng: postcode trung tâm (EC/WC/W1) ô nhiễm NO2 hơn rìa ngoài (BR/RM/CR/KT)
        inner = ctx.scalar(f"SELECT avg(no2) FROM {st} WHERE postcode ~ '^(EC|WC|W1)[0-9]'")
        outer = ctx.scalar(f"SELECT avg(no2) FROM {st} WHERE postcode ~ '^(BR|RM|CR|KT)[0-9]'")
        log.info("    NO2 TB: trung tâm %.1f, rìa ngoài %.1f µg/m³", inner or 0, outer or 0)
        if not (inner and outer and inner > outer):
            raise LoadError(f"NO2 trung tâm ({inner}) không cao hơn rìa ngoài ({outer})")
        ctx.sql("thay mkt_uk.postcode_air", "TRUNCATE mkt_uk.postcode_air")
        n = ctx.sql("ghi mkt_uk.postcode_air", f"""INSERT INTO mkt_uk.postcode_air (postcode, {', '.join(GRIDS)}, release_id)
            SELECT postcode, {', '.join(GRIDS)}, %s FROM {st}""", (ctx.release_id,))
        ctx.drop_stage("air")
        return {"postcodes": n, "no2_inner": round(inner, 1), "no2_outer": round(outer, 1)}
