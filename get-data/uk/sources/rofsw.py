"""EA Risk of Flooding from Surface Water (NaFRA2, England) dạng lưới lớp rủi ro, lấy qua WMS.

Bản vector có 4–12 triệu polygon pixel 2 m mỗi lớp; DSP từ chối tải trọn bộ ("requested too much data") và tải
theo vùng mất ~45 s cho 4 km² → không khả thi cho cả England. Thay vào đó: GetMap theo ô 10 km ở 5 m/pixel với
style SLD tự định nghĩa (mỗi risk_band một màu, không khử răng cưa) → giải mã màu thành mã lớp:
    0 = không có rủi ro, 1 = High (≥ 3,3%/năm), 2 = Medium (1–3,3%), 3 = Low (0,1–1%)
Mỗi ô lưu thành PNG xám 1 kênh + world file (.pgw, EPSG:27700) → GDAL/numpy đọc trực tiếp.
Chỉ tải ô có postcode England (lấy từ mkt_uk.postcode); ô không có rủi ro nào không lưu file.
"""
from __future__ import annotations

import io
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

from common import db
from common.http import get_json, session

from .base import Source

log = logging.getLogger(__name__)

DATASET = "b5aaa28d-6eb9-460e-8d6f-43caa71fbe0e"
WMS = "https://environment.data.gov.uk/spatialdata/nafra2-risk-of-flooding-from-surface-water/wms"
TILE_M = 10_000
RES_M = 5
PX = TILE_M // RES_M
COLORS = {(1, 1, 1): 1, (2, 2, 2): 2, (3, 3, 3): 3}  # màu SLD → mã lớp
BANDS = {"High": "#010101", "Medium": "#020202", "Low": "#030303"}
# High vẽ sau cùng → nếu các band chồng nhau, pixel nhận mức cao nhất
SLD = ('<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld" xmlns:ogc="http://www.opengis.net/ogc">'
       '<NamedLayer><Name>rofsw</Name><UserStyle><FeatureTypeStyle>'
       + "".join(f'<Rule><ogc:Filter><ogc:PropertyIsEqualTo><ogc:PropertyName>risk_band</ogc:PropertyName>'
                 f'<ogc:Literal>{b}</ogc:Literal></ogc:PropertyIsEqualTo></ogc:Filter><PolygonSymbolizer><Fill>'
                 f'<CssParameter name="fill">{c}</CssParameter></Fill></PolygonSymbolizer></Rule>'
                 for b, c in reversed(BANDS.items()))
       + "</FeatureTypeStyle></UserStyle></NamedLayer></StyledLayerDescriptor>")


def tile_name(tx: int, ty: int) -> str:
    return f"rofsw_{tx:03d}_{ty:03d}.png"


def decode(png: bytes):
    """PNG RGBA từ WMS → mảng uint8 mã lớp. Màu lạ (khử răng cưa, đổi style) → lỗi."""
    import numpy as np
    from PIL import Image
    im = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))
    if im.shape[:2] != (PX, PX):
        raise ValueError(f"ảnh {im.shape} khác {PX}×{PX}")
    out = np.zeros(im.shape[:2], dtype=np.uint8)
    opaque = im[..., 3] > 0
    known = np.zeros_like(opaque)
    for rgb, cls in COLORS.items():
        m = opaque & (im[..., 0] == rgb[0]) & (im[..., 1] == rgb[1]) & (im[..., 2] == rgb[2])
        out[m] = cls
        known |= m
    odd = int((opaque & ~known).sum())
    if odd:
        raise ValueError(f"{odd} pixel có màu ngoài bảng lớp (khử răng cưa/style đổi?)")
    return out


class EaRofsw(Source):
    name = "ea_rofsw"
    dataset_id = "uk.ea.rofsw"
    description = "EA Risk of Flooding from Surface Water (NaFRA2): lưới lớp High/Medium/Low 5 m qua WMS (England)"

    def add_arguments(self, p):
        p.add_argument("--workers", type=int, default=2, help="số request WMS song song (mặc định 2)")
        p.add_argument("--pause", type=float, default=0.5, help="nghỉ (giây) trước mỗi request — tường lửa EA chặn khi gọi dồn")

    def plan(self, args):
        meta = get_json(f"https://environment.data.gov.uk/backend/catalog/api/catalog/data-sets/{DATASET}")
        modified = datetime.fromtimestamp(meta["modified"] / 1000, timezone.utc).date()
        return self.release(modified.isoformat(), period_end=modified,
                            meta={"wms": WMS, "tile_m": TILE_M, "res_m": RES_M, "classes": {"1": "High", "2": "Medium", "3": "Low"},
                                  "title": meta.get("title")})

    def tiles(self) -> list[tuple[int, int]]:
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
        log.info("  %s ô %s km có postcode England", len(tiles), TILE_M // 1000)
        done_path = rel.path("tiles_done.json")  # resume: ô đã xử lý (kể cả ô rỗng)
        done = set(map(tuple, json.loads(done_path.read_text()))) if done_path.exists() else set()
        lock = threading.Lock()
        sess = session()
        stats = {"tiles": len(tiles), "with_risk": 0, "pixels": {"1": 0, "2": 0, "3": 0}}

        def fetch(t):
            tx, ty = t
            x0, y0 = tx * TILE_M, ty * TILE_M
            params = {"service": "WMS", "version": "1.1.1", "request": "GetMap", "layers": "rofsw", "styles": "",
                      "srs": "EPSG:27700", "bbox": f"{x0},{y0},{x0 + TILE_M},{y0 + TILE_M}", "width": PX, "height": PX,
                      "format": "image/png; mode=8bit", "transparent": "true", "format_options": "antialias:none",
                      "SLD_BODY": SLD}
            last = None
            for attempt in range(5):
                try:
                    time.sleep(args.pause)
                    r = sess.get(WMS, params=params, timeout=300)
                    if r.status_code != 200 or not r.headers.get("Content-Type", "").startswith("image/png"):
                        raise RuntimeError(f"HTTP {r.status_code} {r.headers.get('Content-Type')}: {r.text[:300]!r}")
                    return t, decode(r.content)
                except Exception as e:  # noqa: BLE001
                    last = e
                    log.warning("  ô %s lần %s lỗi: %s", t, attempt + 1, str(e)[:200])
                    # 403 = tường lửa Azure chặn tạm vì gọi dồn dập → nghỉ lâu
                    time.sleep((120 if "HTTP 403" in str(e) else 10) * (attempt + 1))
            raise RuntimeError(f"Ô {t} (bbox {x0},{y0}) lỗi sau 5 lần: {last}")

        todo = [t for t in tiles if t not in done]
        log.info("  còn %s ô cần tải (%s đã xong)", len(todo), len(done))
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(fetch, t) for t in todo]
            for i, f in enumerate(as_completed(futs), 1):
                (tx, ty), arr = f.result()
                if arr.any():
                    name = tile_name(tx, ty)
                    Image.fromarray(arr, mode="L").save(rel.path(name), optimize=True)
                    # world file: kích thước pixel, xoay, toạ độ TÂM pixel trên-trái (ảnh WMS: hàng 0 ở phía bắc)
                    rel.path(name[:-4] + ".pgw").write_text(
                        f"{RES_M}\n0\n0\n{-RES_M}\n{tx * TILE_M + RES_M / 2}\n{(ty + 1) * TILE_M - RES_M / 2}\n")
                with lock:
                    done.add((tx, ty))
                    if i % 25 == 0 or i == len(todo):
                        done_path.write_text(json.dumps(sorted(done)))
                        log.info("  %s/%s ô", i, len(todo))
        for t in tiles:
            p = rel.dir / tile_name(*t)
            if p.exists():
                arr = np.asarray(Image.open(p))
                stats["with_risk"] += 1
                for k in ("1", "2", "3"):
                    stats["pixels"][k] += int((arr == int(k)).sum())
                rel.add_file(p.name, url=WMS)
                rel.add_file(p.name[:-4] + ".pgw", url=WMS)
        area = {k: round(v * RES_M * RES_M / 1e6, 1) for k, v in stats["pixels"].items()}
        log.info("  %s ô có rủi ro; diện tích km² theo lớp (1=High, 2=Medium, 3=Low): %s", stats["with_risk"], area)
        # NaFRA2: ~ vài nghìn km² England có rủi ro nước mặt; High ít nhất
        if not (area["1"] < area["3"] and 500 < sum(area.values()) < 30_000):
            raise RuntimeError(f"Diện tích rủi ro bất thường: {area}")
        rel.meta.update(stats=stats, area_km2=area)
        done_path.unlink(missing_ok=True)


# ------------------------------------------------------------------ Wales -----
NRW_WFS = "https://datamap.gov.wales/geoserver/ows"
NRW_LAYER = "inspire-nrw:NRW_FLOOD_RISK_FROM_SURFACE_WATER_SMALL_WATERCOURSES"
NRW_RISK = {"High": 3, "Medium": 2, "Low": 1}  # cùng thang với England: High ≥ 3,3%/năm, Medium 1–3,3%, Low 0,1–1%


def nrw_tile_name(tx: int, ty: int) -> str:
    return f"nrw_sw_{tx:03d}_{ty:03d}.json.gz"


class NrwRofsw(Source):
    """NRW Flood Risk from Surface Water & Small Watercourses (Wales) qua WFS, chỉ ô 10 km có postcode Wales.

    Toàn bộ lớp có ~2,8 triệu polygon (5,6 GB GeoJSON) — không cần tải trọn: lọc BBOX theo ô, lấy EPSG:27700
    (toạ độ nguyên, gọn) và lưu mỗi ô một file gzip: [[mức, [vòng ngoài, lỗ...]...], ...]. Polygon cắt qua mép ô
    có mặt ở cả hai ô (nhà chỉ thuộc một ô nên không đếm trùng).
    """

    name = "nrw_rofsw"
    dataset_id = "uk.nrw.rofsw"
    description = "NRW lũ nước mặt & suối nhỏ (Wales): polygon High/Medium/Low theo ô 10 km qua WFS (EPSG:27700)"
    PAGE = 20_000

    def add_arguments(self, p):
        p.add_argument("--workers", type=int, default=3, help="số ô tải song song (mặc định 3)")

    def _get(self, params: dict) -> dict:
        last = None
        for attempt in range(6):
            try:
                return get_json(NRW_WFS, params={"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                                                 "typeNames": NRW_LAYER, **params}, timeout=600)
            except Exception as e:  # noqa: BLE001
                last = e
                log.warning("  WFS lỗi lần %s (%s): %s", attempt + 1, params.get("bbox"), str(e)[:200])
                time.sleep(15 * (attempt + 1))
        raise RuntimeError(f"NRW WFS lỗi sau 6 lần, params={params}: {last}")

    def plan(self, args):
        d = self._get({"outputFormat": "application/json", "count": 1, "srsName": "EPSG:27700"})
        pub = (d["features"][0]["properties"].get("pub_date") or "")[:10] if d.get("features") else ""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", pub):
            raise RuntimeError(f"Không đọc được pub_date của lớp NRW: {d.get('features', [{}])[:1]}")
        return self.release(pub, period_end=date.fromisoformat(pub),
                            meta={"wfs": NRW_WFS, "layer": NRW_LAYER, "tile_m": TILE_M, "risk": NRW_RISK})

    def tiles(self) -> list[tuple[int, int]]:
        c = db.conn()
        if c is None:
            raise RuntimeError("Cần DB (mkt_uk.postcode) để chọn ô có postcode Wales")
        rows = c.execute(f"""
            SELECT DISTINCT floor(ST_X(g) / {TILE_M})::int, floor(ST_Y(g) / {TILE_M})::int
            FROM (SELECT ST_Transform(geom, 27700) g FROM mkt_uk.postcode
                  WHERE country_code = 'W92000004' AND geom IS NOT NULL) x ORDER BY 1, 2""").fetchall()
        return [(int(a), int(b)) for a, b in rows]

    def fetch_tile(self, tx: int, ty: int) -> list:
        x0, y0 = tx * TILE_M, ty * TILE_M
        bbox = f"{x0},{y0},{x0 + TILE_M},{y0 + TILE_M},EPSG:27700"
        feats, start, matched = [], 0, None
        while True:
            d = self._get({"outputFormat": "application/json", "srsName": "EPSG:27700", "bbox": bbox,
                           "count": self.PAGE, "startIndex": start})
            page = d.get("features", [])
            if matched is None and d.get("numberMatched") not in (None, "unknown"):
                matched = int(d["numberMatched"])
            for ft in page:
                risk = NRW_RISK.get((ft.get("properties") or {}).get("risk"))
                g = ft.get("geometry") or {}
                if risk is None:
                    raise RuntimeError(f"Mức rủi ro lạ ở ô {tx},{ty}: {ft.get('properties')}")
                polys = g["coordinates"] if g.get("type") == "MultiPolygon" else [g.get("coordinates")]
                for p in polys:
                    feats.append([risk, [[[int(round(x)), int(round(y))] for x, y, *_ in ring] for ring in p]])
            start += len(page)
            if len(page) < self.PAGE:
                break
        if matched is not None and start != matched:
            raise RuntimeError(f"Ô {tx},{ty}: nhận {start}/{matched} feature")
        return feats

    def download(self, rel, args):
        import gzip
        tiles = self.tiles()
        log.info("  %s ô %s km có postcode Wales", len(tiles), TILE_M // 1000)
        done_path = rel.path("tiles_done.json")
        done = set(map(tuple, json.loads(done_path.read_text()))) if done_path.exists() else set()
        todo = [t for t in tiles if t not in done]
        log.info("  còn %s ô cần tải (%s đã xong)", len(todo), len(done))
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(self.fetch_tile, *t): t for t in todo}
            for i, f in enumerate(as_completed(futs), 1):
                t = futs[f]
                feats = f.result()
                if feats:
                    with gzip.open(rel.path(nrw_tile_name(*t)), "wt") as out:
                        json.dump(feats, out, separators=(",", ":"))
                with lock:
                    done.add(t)
                    if i % 10 == 0 or i == len(todo):
                        done_path.write_text(json.dumps(sorted(done)))
                        log.info("  %s/%s ô", i, len(todo))
        n_poly, n_files = 0, 0
        for t in tiles:
            p = rel.dir / nrw_tile_name(*t)
            if p.exists():
                n_files += 1
                rel.add_file(p.name, url=f"{NRW_WFS}?typeNames={NRW_LAYER}")
        log.info("  %s/%s ô có vùng rủi ro", n_files, len(tiles))
        if n_files < 0.5 * len(tiles):
            raise RuntimeError(f"Chỉ {n_files}/{len(tiles)} ô có vùng rủi ro nước mặt — tải lỗi?")
        rel.meta.update(tiles=len(tiles), tiles_with_risk=n_files)
        done_path.unlink(missing_ok=True)
