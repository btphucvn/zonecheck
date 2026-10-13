"""Defra Strategic Noise Mapping Round 4 (England, 2022): lưới mức ồn (dB) đường bộ, đường sắt, sân bay qua WCS.

DSP không cho tải trọn bộ raster (chỉ "download by area of interest") → GetCoverage theo ô 10 km ở 20 m/pixel
(SCALEFACTOR=0.5 so với lưới gốc 10 m). Mỗi ô lưu thành PNG xám uint8 = round(dB), 0 = không có dữ liệu
(dưới ngưỡng mô hình ~40 dB hoặc ngoài vùng), kèm world file (.pgw, EPSG:27700) đọc từ GeoTIFF trả về.
Chỉ tải ô có postcode England; ô không có giá trị nào không lưu file.
"""
from __future__ import annotations

import io
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from common import db
from common.http import get_json, session

from .base import Source

log = logging.getLogger(__name__)

SP = "https://environment.data.gov.uk/spatialdata"
# khoá → (dataset DSP, WCS, coverageId)
COVERAGES = {
    "road_lden": ("562c9d56-7c2d-4d42-83bb-578d6e97a517", f"{SP}/road-noise-all-metrics-england-round-4/wcs",
                  "Road_Noise_Lden_England_Round_4_All"),
    "road_lnight": ("562c9d56-7c2d-4d42-83bb-578d6e97a517", f"{SP}/road-noise-all-metrics-england-round-4/wcs",
                    "Road_Noise_Lnight_England_Round_4_All"),
    "rail_lden": ("3fb3c2d7-292c-4e0a-bd5b-d8e4e1fe2947", f"{SP}/noise-data/wcs", "Rail_Noise_Lden_England_Round_4_All"),
    "rail_lnight": ("3fb3c2d7-292c-4e0a-bd5b-d8e4e1fe2947", f"{SP}/noise-data/wcs", "Rail_Noise_Lnight_England_Round_4_All"),
    "airport_lden": ("dac9cba4-abe7-43bd-b8e9-8a83da52edd8", f"{SP}/airport-noise-all-metrics-england-round-4/wcs",
                     "Airport_Noise_ALL_Lden"),
    "airport_lnight": ("dac9cba4-abe7-43bd-b8e9-8a83da52edd8", f"{SP}/airport-noise-all-metrics-england-round-4/wcs",
                       "Airport_Noise_ALL_Lnight"),
}
TILE_M = 10_000
SCALE = 0.5  # lưới gốc 10 m → 20 m


def _gdal_float32(tif: bytes) -> bytes:
    import os
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in.tif"), os.path.join(d, "out.tif")
        with open(src, "wb") as f:
            f.write(tif)
        p = subprocess.run(["gdal_translate", "-q", "-ot", "Float32", src, dst], capture_output=True, text=True)
        if p.returncode != 0:
            raise ValueError(f"gdal_translate lỗi: {p.stderr[-500:]}")
        with open(dst, "rb") as f:
            return f.read()


def decode(tif: bytes):
    """GeoTIFF float32 → (uint8 dB, world file). Đọc toạ độ gốc + kích thước pixel từ tag GeoTIFF."""
    import numpy as np
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(tif))
    except Exception:  # noqa: BLE001 — PIL không đọc Float64 (lớp sân bay): chuyển sang Float32 bằng GDAL
        im = Image.open(io.BytesIO(_gdal_float32(tif)))
    scale = im.tag_v2.get(33550)  # ModelPixelScale (sx, sy, sz)
    tie = im.tag_v2.get(33922)    # ModelTiepoint (i, j, k, x, y, z)
    mtx = im.tag_v2.get(34264)    # ModelTransformation 4×4 (ô bị cắt ở rìa coverage dùng tag này)
    if scale and tie:
        sx, sy, x0, y0 = float(scale[0]), float(scale[1]), float(tie[3]), float(tie[4])
    elif mtx:
        sx, sy, x0, y0 = float(mtx[0]), -float(mtx[5]), float(mtx[3]), float(mtx[7])
        if mtx[1] or mtx[4]:
            raise ValueError("GeoTIFF bị xoay, không hỗ trợ")
    else:
        raise ValueError(f"GeoTIFF thiếu tag toạ độ: {sorted(im.tag_v2.keys())}")
    a = np.asarray(im, dtype="float32")
    a = np.where(np.isfinite(a) & (a > 0) & (a < 1e6), a, 0)  # nodata của lớp sân bay = 3.4e38
    if a.max() > 140:
        raise ValueError(f"giá trị dB bất thường: max {a.max()}")
    out = np.rint(a).astype("uint8")
    world = f"{sx}\n0\n0\n{-sy}\n{x0 + sx / 2}\n{y0 - sy / 2}\n"
    return out, world


class DefraNoise(Source):
    name = "defra_noise"
    dataset_id = "uk.defra.noise_r4"
    description = "Defra Strategic Noise Round 4 (England): lưới dB đường bộ/đường sắt/sân bay (Lden, Lnight), ô 10 km × 20 m qua WCS"

    def add_arguments(self, p):
        p.add_argument("--layers", help=f"chỉ tải các lớp (phẩy): {','.join(COVERAGES)}")
        p.add_argument("--workers", type=int, default=2)
        p.add_argument("--pause", type=float, default=0.3, help="nghỉ (giây) trước mỗi request")

    def plan(self, args):
        mods = []
        for ds in sorted({c[0] for c in COVERAGES.values()}):
            m = get_json(f"https://environment.data.gov.uk/backend/catalog/api/catalog/data-sets/{ds}")
            mods.append(datetime.fromtimestamp(m["modified"] / 1000, timezone.utc).date())
        v = max(mods)
        self._layers = args.layers.split(",") if getattr(args, "layers", None) else list(COVERAGES)
        return self.release(v.isoformat(), period_end="2022-12-31",
                            meta={"round": 4, "tile_m": TILE_M, "res_m": 10 / SCALE, "layers": self._layers,
                                  "encoding": "uint8 = round(dB), 0 = không có dữ liệu"})

    def tiles(self):
        c = db.conn()
        if c is None:
            raise RuntimeError("Cần DB (mkt_uk.postcode) để chọn ô có postcode England")
        rows = c.execute(f"""
            SELECT DISTINCT floor(ST_X(g) / {TILE_M})::int, floor(ST_Y(g) / {TILE_M})::int
            FROM (SELECT ST_Transform(geom, 27700) g FROM mkt_uk.postcode
                  WHERE country_code = 'E92000001' AND geom IS NOT NULL) x ORDER BY 1, 2""").fetchall()
        return [(int(a), int(b)) for a, b in rows]

    def download(self, rel, args):
        import numpy as np
        from PIL import Image
        tiles = self.tiles()
        log.info("  %s ô %s km có postcode England, %s lớp", len(tiles), TILE_M // 1000, len(self._layers))
        sess = session()
        done_path = rel.path("tiles_done.json")
        done = {tuple(x) for x in json.loads(done_path.read_text())} if done_path.exists() else set()
        lock = threading.Lock()

        def fetch(job):
            layer, (tx, ty) = job
            ds, wcs, cov = COVERAGES[layer]
            x0, y0 = tx * TILE_M, ty * TILE_M
            params = {"service": "WCS", "version": "2.0.1", "request": "GetCoverage", "coverageId": f"{ds}__{cov}",
                      "format": "image/tiff", "SCALEFACTOR": SCALE,
                      "subset": [f"E({x0},{x0 + TILE_M})", f"N({y0},{y0 + TILE_M})"]}
            last = None
            for attempt in range(6):
                try:
                    time.sleep(args.pause)
                    r = sess.get(wcs, params=params, timeout=300)
                    ct = r.headers.get("Content-Type", "")
                    if r.status_code != 200 or "tiff" not in ct:
                        # ô nằm ngoài phạm vi coverage → server trả lỗi OGC; coi là ô rỗng
                        if "subset" in r.text.lower() and ("outside" in r.text.lower() or "intersect" in r.text.lower()):
                            return job, None, None
                        raise RuntimeError(f"HTTP {r.status_code} {ct}: {r.text[:300]!r}")
                    arr, world = decode(r.content)
                    return job, arr, world
                except Exception as e:  # noqa: BLE001
                    last = e
                    log.warning("  %s ô %s lần %s lỗi: %s", layer, (tx, ty), attempt + 1, str(e)[:200])
                    time.sleep((120 if "HTTP 403" in str(e) or "HTTP 429" in str(e) else 10) * (attempt + 1))
            raise RuntimeError(f"{layer} ô {(tx, ty)} lỗi sau 6 lần: {last}")

        # phạm vi từng coverage (lớp sân bay chỉ phủ quanh các sân bay): ô ngoài phạm vi → server trả HTTP 500
        import re as _re
        extents = {}
        for layer in self._layers:
            ds, wcs, cov = COVERAGES[layer]
            xml = sess.get(wcs, params={"service": "WCS", "version": "2.0.1", "request": "DescribeCoverage",
                                        "coverageId": f"{ds}__{cov}"}, timeout=120).text
            lo = _re.search(r"<gml:lowerCorner>([\d.]+) ([\d.]+)", xml)
            hi = _re.search(r"<gml:upperCorner>([\d.]+) ([\d.]+)", xml)
            if not lo or not hi:
                raise RuntimeError(f"DescribeCoverage {cov}: không đọc được phạm vi: {xml[:300]!r}")
            extents[layer] = (float(lo.group(1)), float(lo.group(2)), float(hi.group(1)), float(hi.group(2)))
        log.info("  phạm vi coverage: %s", extents)

        def inside(layer, t):
            x0, y0, x1, y1 = extents[layer]
            return t[0] * TILE_M < x1 and (t[0] + 1) * TILE_M > x0 and t[1] * TILE_M < y1 and (t[1] + 1) * TILE_M > y0

        jobs = [(layer, t) for layer in self._layers for t in tiles if (layer, *t) not in done and inside(layer, t)]
        log.info("  còn %s ô×lớp cần tải (%s đã xong)", len(jobs), len(done))
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(fetch, j) for j in jobs]
            for i, f in enumerate(as_completed(futs), 1):
                (layer, (tx, ty)), arr, world = f.result()
                if arr is not None and arr.any():
                    name = f"{layer}_{tx:03d}_{ty:03d}.png"
                    Image.fromarray(arr, mode="L").save(rel.path(name), optimize=True)
                    rel.path(name[:-4] + ".pgw").write_text(world)
                with lock:
                    done.add((layer, tx, ty))
                    if i % 50 == 0 or i == len(jobs):
                        done_path.write_text(json.dumps(sorted(done)))
                        log.info("  %s/%s", i, len(jobs))
        stats = {}
        for layer in self._layers:
            files = sorted(rel.dir.glob(f"{layer}_*.png"))
            px55 = 0
            for p in files:
                a = np.asarray(Image.open(p))
                px55 += int((a >= 55).sum())
                rel.add_file(p.name, url=COVERAGES[layer][1])
                rel.add_file(p.name[:-4] + ".pgw", url=COVERAGES[layer][1])
            stats[layer] = {"tiles": len(files), "km2_ge55db": round(px55 * (10 / SCALE) ** 2 / 1e6, 1)}
        log.info("  thống kê: %s", stats)
        # kiểm tra: đường bộ phủ gần hết các ô có dân cư; diện tích ≥ 55 dB Lden đường bộ cỡ nghìn km²
        if "road_lden" in stats:
            s = stats["road_lden"]
            if s["tiles"] < 0.8 * len(tiles) or not (500 < s["km2_ge55db"] < 60_000):
                raise RuntimeError(f"road_lden bất thường: {s} (số ô có postcode {len(tiles)})")
        rel.meta["stats"] = stats
        done_path.unlink(missing_ok=True)
