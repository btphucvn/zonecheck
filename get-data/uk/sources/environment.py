"""Rủi ro môi trường bổ sung (lấp khoảng trống so với đối thủ, xem DATA_GAP_TRACKER.md):

- EA qua data.gov.uk (CKAN) → link tải trực tiếp của Defra Data Services Platform: bãi rác, sự cố ô nhiễm,
  xói lở bờ biển, lũ đã xảy ra, công trình chống lũ, lũ hồ chứa, RoFRS theo postcode, xả tràn nước thải.
- NRW (Wales) qua WFS GeoServer của DataMapWales.
- Coal Authority (Mining Remediation Authority) qua ArcGIS FeatureServer.
- BGS (radon, GeoSure, mỏ không phải than) qua OS Downloads API.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
from datetime import date

from common.http import get_json
from common.sources import os_product_downloads

from .base import Source
from .zones import ArcgisZones

log = logging.getLogger(__name__)

CKAN = "https://ckan.publishing.service.gov.uk/api/action/package_show"


def ckan_package(name: str) -> dict:
    d = get_json(CKAN, params={"id": name})
    if not d.get("success"):
        raise RuntimeError(f"CKAN package_show {name} không thành công: {str(d)[:300]}")
    return d["result"]


def resource_filename(url: str) -> str:
    """DSP: .../api/file/download?fileDataSetId=..&fileName=X → X; còn lại lấy đoạn cuối của path."""
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    name = q.get("fileName", [None])[0] or url.split("?")[0].rstrip("/").split("/")[-1]
    return urllib.parse.unquote(name).replace(" ", "_")


class CkanFiles(Source):
    """Tải các resource của một hoặc nhiều package data.gov.uk, lọc URL bằng regex.

    packages: {tên package CKAN: regex trên URL resource}. Phiên bản = ngày metadata_modified mới nhất.
    """

    def __init__(self, name, dataset_id, packages: dict[str, str], description, min_files=1):
        self.name = name
        self.dataset_id = dataset_id
        self.packages = packages
        self.description = description
        self.min_files = min_files

    def plan(self, args):
        self._res, modified = [], []
        for pkg, pat in self.packages.items():
            p = ckan_package(pkg)
            modified.append(p.get("metadata_modified", "")[:10])
            hits = [r["url"] for r in p.get("resources", []) if r.get("url") and re.search(pat, r["url"])]
            if not hits:
                raise RuntimeError(f"Package {pkg}: không resource nào khớp {pat!r}. Có: "
                                   f"{[r.get('url') for r in p.get('resources', [])][:12]}")
            self._res += hits
        if len(self._res) < self.min_files:
            raise RuntimeError(f"Chỉ thấy {len(self._res)} file, cần ≥ {self.min_files}")
        v = max(modified) or date.today().isoformat()
        return self.release(v, period_end=v, meta={"packages": self.packages, "files": [resource_filename(u) for u in self._res]})

    def download(self, rel, args):
        for url in self._res:
            rel.download(url.replace(" ", "%20"), resource_filename(url))


EA_SOURCES = [
    CkanFiles("ea_landfill", "uk.ea.landfill", {
        "historic-landfill-sites1": r"Historic_Landfill_Sites\.geojson\.zip$",
        "permitted-waste-sites-authorised-landfill-site-boundaries1": r"Boundaries\.geojson\.zip$",
    }, "EA bãi rác cũ (Historic Landfill) + bãi rác đang cấp phép (Authorised Landfill), polygon (England)", min_files=2),
    CkanFiles("ea_pollution_incidents", "uk.ea.pollution_incidents", {
        "environmental-pollution-incidents-category-1-and-21": r"Environmental_Pollution_Incidents\.zip$",
    }, "EA sự cố ô nhiễm môi trường mức 1–2 (điểm, England)"),
    CkanFiles("ea_coastal_erosion", "uk.ea.ncerm", {
        "national-coastal-erosion-risk-mapping-ncerm-national-2024": r"NCERM_National_2024\.geojson\.zip$",
        "national-coastal-erosion-risk-mapping-ncerm-key-summary-information": r"\.xlsx$",
    }, "EA National Coastal Erosion Risk Mapping 2024: đường bờ dự báo xói lở (England)"),
    CkanFiles("ea_flood_history", "uk.ea.flood_history", {
        "recorded-flood-outlines1": r"Recorded_Flood_Outlines\.geojson\.zip$",
        "historic-flood-map1": r"Historic_Flood_Map\.geojson\.zip$",
    }, "EA lũ đã xảy ra: Recorded Flood Outlines (từng đợt) + Historic Flood Map (gộp) (England)", min_files=2),
    CkanFiles("ea_flood_defences", "uk.ea.flood_defences", {
        "aims-spatial-flood-defences-inc-standardised-attributes": r"attributes\.geojson\.zip$",
    }, "EA AIMS Spatial Flood Defences: đê, tường chống lũ kèm tình trạng (England)"),
    CkanFiles("ea_rofrs_postcodes", "uk.ea.rofrs_postcodes", {
        "risk-of-flooding-from-rivers-and-sea-postcodes-in-areas-at-risk2": r"\.zip$",
        "risk-of-flooding-from-rivers-and-sea-properties-in-areas-at-risk2": r"\.zip$",
    }, "EA NaFRA2 Risk of Flooding from Rivers and Sea: số nhà theo mức rủi ro cho từng postcode (England)", min_files=2),
    CkanFiles("ea_storm_overflows", "uk.ea.storm_overflows", {
        "event-duration-monitoring-storm-overflows-annual-returns": r"(EDM_20\d\d_Storm_Overflow_Annual_Return|Long-term%20Trends|Long-term Trends)",
    }, "EA Event Duration Monitoring: số lần/giờ xả tràn nước thải theo điểm xả, các năm (England)", min_files=3),
]


class WfsLayers(Source):
    """Tải layer WFS 2.0 (GeoServer) ra GeoJSON EPSG:4326, phân trang startIndex/count, kiểm tra tổng số feature."""

    def __init__(self, name, dataset_id, base, layers: dict[str, str], description, page=5000):
        self.name = name
        self.dataset_id = dataset_id
        self.base = base
        self.layers = layers  # tên file → typeName
        self.description = description
        self.page = page

    def plan(self, args):
        return self.release(date.today().isoformat(), period_end=date.today(), meta={"wfs": self.base, "layers": self.layers})

    def _get(self, params):
        import time
        for attempt in range(6):
            try:
                return get_json(self.base, params={"service": "WFS", "version": "2.0.0", "request": "GetFeature", **params},
                                timeout=600)
            except Exception as e:  # noqa: BLE001
                if attempt == 5:
                    raise
                log.warning("    WFS lỗi (%s), thử lại", str(e)[:200])
                time.sleep(10 * (attempt + 1))

    def download(self, rel, args):
        from common.http import get_text
        for fname, typename in self.layers.items():
            # resultType=hits chỉ trả XML (không có JSON) → đọc thuộc tính numberMatched
            xml = get_text(self.base, params={"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                                              "typeNames": typename, "resultType": "hits"}, timeout=600)
            m = re.search(r'numberMatched="(\d+)"', xml)
            if not m:
                raise RuntimeError(f"WFS hits {typename}: không đọc được numberMatched: {xml[:300]!r}")
            total = int(m.group(1))
            dest = rel.path(fname)
            n = 0
            with open(dest.with_name(fname + ".part"), "w") as f:
                f.write('{"type":"FeatureCollection","features":[\n')
                while True:
                    d = self._get({"typeNames": typename, "outputFormat": "application/json", "srsName": "EPSG:4326",
                                   "count": self.page, "startIndex": n})
                    feats = d.get("features", [])
                    for ft in feats:
                        f.write(("," if n else "") + json.dumps(ft, separators=(",", ":")) + "\n")
                        n += 1
                    if total == 0 and d.get("numberMatched") not in (None, "unknown"):
                        total = int(d["numberMatched"])
                    if len(feats) < self.page:
                        break
                f.write("]}\n")
            if total and n != total:
                raise RuntimeError(f"{typename}: nhận {n}/{total} feature")
            if n == 0:
                raise RuntimeError(f"{typename}: không có feature nào")
            dest.with_name(fname + ".part").replace(dest)
            log.info("  %s: %s feature", typename, f"{n:,}")
            rel.add_file(fname, f"{self.base}?typeNames={typename}")
            rel.meta.setdefault("counts", {})[fname] = n


NRW_WFS = "https://datamap.gov.wales/geoserver/ows"

NRW_SOURCES = [
    WfsLayers("nrw_flood", "uk.nrw.flood", NRW_WFS, {
        "flood_risk_rivers.geojson": "inspire-nrw:NRW_FLOOD_RISK_FROM_RIVERS",
        "flood_risk_sea.geojson": "inspire-nrw:NRW_FLOOD_RISK_FROM_SEA",
        "flood_risk_surface_water.geojson": "inspire-nrw:NRW_FLOOD_RISK_FROM_SURFACE_WATER_SMALL_WATERCOURSES",
        "floodzone_rivers_seas.geojson": "inspire-nrw:NRW_FLOODZONE_RIVERS_SEAS_MERGED",
        "historic_floodmap.geojson": "inspire-nrw:NRW_HISTORIC_FLOODMAP",
        "historic_landfill.geojson": "inspire-nrw:NRW_Historic_Landfill_Sites",
        "flood_warning_areas.geojson": "inspire-nrw:NRW_FLOOD_WARNING",
    }, "NRW (Wales): rủi ro lũ sông/biển/nước mặt, Flood Map for Planning, lũ đã xảy ra, bãi rác cũ, khu cảnh báo lũ"),
]

COAL = "https://services-eu1.arcgis.com/Qn4lKcPDVHNivEyr/arcgis/rest/services"

COAL_SOURCES = [
    ArcgisZones("coal_authority", "uk.coal.risk_areas", {
        "development_high_risk_area.geojson": f"{COAL}/DevelopmentHighRiskArea/FeatureServer/0",
        "development_low_risk_area.geojson": f"{COAL}/DevelopmentLowRiskArea/FeatureServer/0",
        "coalfield_consultation_areas.geojson": f"{COAL}/Coalfield_Consultation_Areas/FeatureServer/0",
    }, "Mining Remediation Authority (Coal Authority): vùng rủi ro mỏ than cao/thấp (≈ Coal Mining Reporting Area), GB",
        workers=2, precision=6),
]


class BgsOpenData(Source):
    """Sản phẩm BGS phát hành qua OS Downloads API (OGL, có md5). Lấy GeoPackage; area None = mọi vùng (GB + NI)."""

    def __init__(self, name, dataset_id, product, description, fmt="GeoPackage", area="GB"):
        self.name = name
        self.dataset_id = dataset_id
        self.product = product
        self.description = description
        self.fmt = fmt
        self.area = area

    def plan(self, args):
        info, files = os_product_downloads(self.product, self.area, self.fmt)
        if not files:
            raise RuntimeError(f"OS Downloads {self.product}: không có file {self.area}/{self.fmt}")
        self._files = files
        v = re.sub(r"[^\w.-]+", "_", str(info.get("version") or "latest")).strip("_")
        return self.release(v, meta={"product": self.product, "format": self.fmt, "version": info.get("version")})

    def download(self, rel, args):
        for f in self._files:
            rel.download(f["url"], f["fileName"], expect_md5=f.get("md5"))


BGS_SOURCES = [
    BgsOpenData("bgs_radon", "uk.bgs.radon", "Radon_Indicative_Atlas",
                "BGS/UKHSA Indicative Atlas of Radon: lớp % nhà vượt ngưỡng, ô 1 km (GB, OGL)"),
    BgsOpenData("bgs_geosure_hex", "uk.bgs.geosure_hex", "GB-Hex-5km-GeoSure",
                "BGS GeoSure 5 km hex: co ngót đất sét, sạt lở, hoà tan, đất lún, cát chảy, nén (GB, OGL)"),
    BgsOpenData("bgs_mining_hazard", "uk.bgs.mining_hazard", "GB-Hex-1km-Mining-Haz",
                "BGS mức nguy cơ mỏ (không gồm than), hex 1 km (GB, OGL)"),
]


class EaReservoirWms(Source):
    """EA Reservoir Flood Extents (ngày mưa + ngày khô) dạng mặt nạ 10 m qua WMS.

    File tải trọn bộ 3,4 GB/bản bị server cắt sau ~1 GB và không hỗ trợ tải tiếp (Range) → GetMap theo ô 10 km với SLD tô
    kín một màu, chỉ cho ô có postcode England. Mỗi ô lưu PNG xám: bit 1 = trong vùng ngập ngày khô, bit 2 = ngày mưa.
    """

    name = "ea_reservoir_flood"
    dataset_id = "uk.ea.reservoir_flood"
    description = "EA Reservoir Flood Extents (ngày mưa + ngày khô): mặt nạ 10 m qua WMS, ô 10 km có postcode (England)"
    LAYERS = {1: ("reservoir-flood-extents-dry-day", "Reservoir_Flood_Extents_Dry_Day"),
              2: ("reservoir-flood-extents-wet-day", "Reservoir_Flood_Extents_Wet_Day")}
    TILE_M, PX = 10_000, 1000

    def add_arguments(self, p):
        p.add_argument("--workers", type=int, default=2)
        p.add_argument("--pause", type=float, default=0.3)

    def plan(self, args):
        # catalog DSP không có mục cho id tải file → phiên bản theo ngày lấy
        v = date.today()
        return self.release(v.isoformat(), period_end=v, meta={"tile_m": self.TILE_M, "res_m": self.TILE_M / self.PX,
                                                                "encoding": "bit 1 = dry day, bit 2 = wet day"})

    def download(self, rel, args):
        import io
        import json as _json
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed

        import numpy as np
        from PIL import Image

        from common import db
        from common.http import session
        c = db.conn()
        if c is None:
            raise RuntimeError("Cần DB (mkt_uk.postcode) để chọn ô")
        T = self.TILE_M
        tiles = [(int(a), int(b)) for a, b in c.execute(f"""
            SELECT DISTINCT floor(ST_X(g) / {T})::int, floor(ST_Y(g) / {T})::int
            FROM (SELECT ST_Transform(geom, 27700) g FROM mkt_uk.postcode
                  WHERE country_code = 'E92000001' AND geom IS NOT NULL) x ORDER BY 1, 2""").fetchall()]
        done_path = rel.path("tiles_done.json")
        done = {tuple(x) for x in _json.loads(done_path.read_text())} if done_path.exists() else set()
        sess, lock = session(), threading.Lock()

        def sld(name):
            return ('<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld" '
                    'xmlns:ogc="http://www.opengis.net/ogc"><NamedLayer><Name>' + name + '</Name><UserStyle>'
                    '<FeatureTypeStyle><Rule><PolygonSymbolizer><Fill><CssParameter name="fill">#010101</CssParameter>'
                    '</Fill></PolygonSymbolizer></Rule></FeatureTypeStyle></UserStyle></NamedLayer></StyledLayerDescriptor>')

        def fetch(t):
            tx, ty = t
            out = np.zeros((self.PX, self.PX), dtype=np.uint8)
            for bit, (svc, layer) in self.LAYERS.items():
                params = {"service": "WMS", "version": "1.1.1", "request": "GetMap", "layers": layer, "styles": "",
                          "srs": "EPSG:27700", "bbox": f"{tx * T},{ty * T},{(tx + 1) * T},{(ty + 1) * T}",
                          "width": self.PX, "height": self.PX, "format": "image/png; mode=8bit", "transparent": "true",
                          "format_options": "antialias:none", "SLD_BODY": sld(layer)}
                url = f"https://environment.data.gov.uk/spatialdata/{svc}/wms"
                for attempt in range(6):
                    try:
                        time.sleep(args.pause)
                        r = sess.get(url, params=params, timeout=300)
                        if r.status_code != 200 or not r.headers.get("Content-Type", "").startswith("image/png"):
                            raise RuntimeError(f"HTTP {r.status_code} {r.headers.get('Content-Type')}: {r.text[:200]!r}")
                        im = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA"))
                        out |= np.where(im[..., 3] > 0, bit, 0).astype(np.uint8)
                        break
                    except Exception as e:  # noqa: BLE001
                        if attempt == 5:
                            raise RuntimeError(f"Ô {t} lớp {layer} lỗi sau 6 lần: {e}") from e
                        log.warning("  ô %s %s lần %s lỗi: %s", t, layer, attempt + 1, str(e)[:200])
                        time.sleep((120 if "HTTP 403" in str(e) else 10) * (attempt + 1))
            return t, out

        todo = [t for t in tiles if t not in done]
        log.info("  %s ô có postcode England, còn %s ô", len(tiles), len(todo))
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for i, f in enumerate(as_completed([ex.submit(fetch, t) for t in todo]), 1):
                (tx, ty), arr = f.result()
                if arr.any():
                    name = f"reservoir_{tx:03d}_{ty:03d}.png"
                    Image.fromarray(arr, mode="L").save(rel.path(name), optimize=True)
                    res = T / self.PX
                    rel.path(name[:-4] + ".pgw").write_text(f"{res}\n0\n0\n{-res}\n{tx * T + res / 2}\n{(ty + 1) * T - res / 2}\n")
                with lock:
                    done.add((tx, ty))
                    if i % 50 == 0 or i == len(todo):
                        done_path.write_text(_json.dumps(sorted(done)))
                        log.info("  %s/%s", i, len(todo))
        files = sorted(rel.dir.glob("reservoir_*.png"))
        km2 = {1: 0.0, 2: 0.0}
        for p in files:
            a = np.asarray(Image.open(p))
            for bit in km2:
                km2[bit] += float(((a & bit) > 0).sum()) * (T / self.PX) ** 2 / 1e6
            rel.add_file(p.name)
            rel.add_file(p.name[:-4] + ".pgw")
        log.info("  %s ô có vùng ngập; km² ngày khô %.0f, ngày mưa %.0f", len(files), km2[1], km2[2])
        # vùng ngập do vỡ hồ chứa ở England: vài nghìn km² (ngày mưa ≥ ngày khô vì cộng thêm lũ sông)
        if not (len(files) > 100 and 300 < km2[2] < 30_000 and km2[1] <= km2[2] * 1.2):
            raise RuntimeError(f"Diện tích vùng ngập hồ chứa bất thường: {km2}, {len(files)} ô")
        rel.meta.update(tiles_with_extent=len(files), km2={"dry": round(km2[1]), "wet": round(km2[2])})
        done_path.unlink(missing_ok=True)


EA_SOURCES.append(EaReservoirWms())
