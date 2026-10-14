"""Địa lý: ONSPD, OS OpenData (Code-Point Open, Open Names, Open UPRN, Open Greenspace), ranh giới ONS."""
from __future__ import annotations

import logging
import re

from common.sources import (
    arcgis_export_geojson, arcgis_item_data_url, arcgis_search, os_product_downloads, parse_month_year,
)

from .base import Source

log = logging.getLogger(__name__)


class Onspd(Source):
    name = "onspd"
    dataset_id = "uk.ons.onspd"
    description = "ONS Postcode Directory: postcode → toạ độ, OA/LSOA/MSOA/LAD (zip CSV, theo quý)"

    def plan(self, args):
        items = arcgis_search('title:"ONS Postcode Directory"', item_type="CSV Collection")
        best = None
        for it in items:
            m = re.fullmatch(r"ONS Postcode Directory \((\w+ \d{4})\)", it["title"].strip())
            if m and (d := parse_month_year(m.group(1))) and (best is None or d > best[0]):
                best = (d, it)
        if not best:
            raise RuntimeError(f"Không tìm thấy ONSPD trên ArcGIS. Tiêu đề trả về: {[i['title'] for i in items]}")
        d, it = best
        self._item = it
        return self.release(d.strftime("%Y-%m"), period_end=d.date(),
                            meta={"arcgis_item": it["id"], "title": it["title"]})

    def download(self, rel, args):
        rel.download(arcgis_item_data_url(self._item["id"]), f"ONSPD_{rel.version}.zip")


class OsOpenData(Source):
    """Sản phẩm OS OpenData qua OS Downloads API (không cần key, có md5)."""

    def __init__(self, name, product, fmt, description):
        self.name = name
        self.product = product
        self.fmt = fmt
        self.dataset_id = f"uk.os.{name.removeprefix('os_')}"
        self.description = description

    def plan(self, args):
        info, files = os_product_downloads(self.product, "GB", self.fmt)
        if not files:
            raise RuntimeError(f"OS {self.product}: không có file GB/{self.fmt} (version {info.get('version')})")
        self._files = files
        return self.release(info.get("version") or info.get("productVersion") or "latest",
                            meta={"product": self.product, "format": self.fmt})

    def download(self, rel, args):
        for f in self._files:
            rel.download(f["url"], f["fileName"], expect_md5=f.get("md5"))


OS_SOURCES = [
    OsOpenData("os_codepoint_open", "CodePointOpen", "CSV",
               "OS Code-Point Open: toạ độ postcode GB (OGL, dự phòng cho ONSPD)"),
    OsOpenData("os_open_names", "OpenNames", "CSV", "OS Open Names: địa danh, thị trấn, đường (tìm kiếm theo tên)"),
    OsOpenData("os_open_uprn", "OpenUPRN", "CSV", "OS Open UPRN: toạ độ UPRN (ghép PPD/EPC)"),
    OsOpenData("os_open_greenspace", "OpenGreenspace", "GeoPackage", "OS Open Greenspace: công viên, sân chơi"),
    OsOpenData("os_boundary_line", "BoundaryLine", "GeoPackage",
               "OS Boundary-Line: ward, khu bầu cử Westminster, county, parish… kèm tên (GB)"),
    OsOpenData("os_built_up_areas", "BuiltUpAreas", "GeoPackage", "OS Open Built Up Areas: ranh giới khu đô thị (GB)"),
    OsOpenData("os_open_roads", "OpenRoads", "GeoPackage", "OS Open Roads: mạng đường GB (motorway, A, B…), đường gần nhất và tiếng ồn"),
]


class OnsBoundary(Source):
    """Ranh giới ONS Open Geography (BGC = generalised 20 m), xuất GeoJSON EPSG:4326 qua FeatureServer."""

    def __init__(self, level, title_prefix, title_suffix, description):
        self.level = level
        self.name = f"boundaries_{level}"
        self.dataset_id = f"uk.ons.boundaries_{level}"
        self.title_prefix = title_prefix
        self.title_suffix = title_suffix
        self.description = description

    def plan(self, args):
        items = arcgis_search(f'title:"{self.title_prefix}" AND title:"{self.title_suffix}"',
                              item_type="Feature Service", num=100)
        pat = re.compile(rf"{re.escape(self.title_prefix)} \((\w+ \d{{4}})\) {re.escape(self.title_suffix)}"
                         r"(?: \(V(\d+)\))?")
        best = None
        for it in items:
            m = pat.fullmatch(it["title"].strip())
            if not m:
                continue
            key = (parse_month_year(m.group(1)), int(m.group(2) or 1))
            if key[0] and (best is None or key > best[0]):
                best = (key, it)
        if not best:
            raise RuntimeError(f"Không tìm thấy ranh giới {self.level} trên ArcGIS (regex {pat.pattern}). "
                               f"Tiêu đề trả về: {[i['title'] for i in items][:20]}")
        (d, ver), it = best
        self._item = it
        return self.release(f"{d:%Y-%m}-v{ver}", period_end=d.date(),
                            meta={"arcgis_item": it["id"], "title": it["title"], "service": it["url"]})

    def download(self, rel, args):
        layer = self._item["url"].rstrip("/") + "/0"
        fname = f"{self.name}_{rel.version}.geojson"
        rel.row_count = arcgis_export_geojson(layer, rel.path(fname))
        rel.add_file(fname, layer)


BOUNDARY_SOURCES = [
    OnsBoundary("oa21", "Output Areas", "Boundaries EW BGC", "Ranh giới Output Area 2021 (E&W, ~189k)"),
    OnsBoundary("lsoa21", "Lower layer Super Output Areas", "Boundaries EW BGC", "Ranh giới LSOA 2021 (E&W, ~35,7k)"),
    OnsBoundary("msoa21", "Middle layer Super Output Areas", "Boundaries EW BGC", "Ranh giới MSOA 2021 (E&W, ~7,3k)"),
    OnsBoundary("lad", "Local Authority Districts", "Boundaries UK BGC", "Ranh giới Local Authority District mới nhất (UK)"),
    OnsBoundary("rgn", "Regions", "Boundaries EN BGC", "Ranh giới Region mới nhất (England)"),
    OnsBoundary("ward", "Wards", "Boundaries UK BGC", "Ranh giới ward bầu cử mới nhất (UK), cùng phiên bản mã với ONSPD"),
]
