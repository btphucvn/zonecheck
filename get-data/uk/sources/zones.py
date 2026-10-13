"""Vùng polygon: quy hoạch (planning.data.gov.uk), thiên nhiên (Natural England), lũ (EA Flood Map for Planning)."""
from __future__ import annotations

import logging
from datetime import date

from common.http import head
from common.sources import arcgis_export_geojson

from .base import Source

log = logging.getLogger(__name__)

PLANNING = "https://files.planning.data.gov.uk/dataset"
NE = "https://services.arcgis.com/JJzESW51TqeY9uat/arcgis/rest/services"
EA = "https://services1.arcgis.com/JZM7qJpmv7vJ0Hzx/arcgis/rest/services"


class PlanningData(Source):
    name = "planning_data"
    dataset_id = "uk.mhclg.planning_data"
    description = "planning.data.gov.uk: conservation area, Article 4, green belt, TPO zone (polygon) + listed building (điểm)"

    DATASETS = ["conservation-area", "article-4-direction-area", "green-belt", "tree-preservation-zone", "listed-building"]

    def plan(self, args):
        # planning.data cập nhật liên tục → phiên bản theo ngày Last-Modified mới nhất của các file
        lm = max(head(f"{PLANNING}/{d}.geojson").headers.get("Last-Modified", "") for d in self.DATASETS)
        from email.utils import parsedate_to_datetime
        v = parsedate_to_datetime(lm).date() if lm else date.today()
        return self.release(v.isoformat(), period_end=v, meta={"datasets": self.DATASETS})

    def download(self, rel, args):
        for d in self.DATASETS:
            rel.download(f"{PLANNING}/{d}.geojson", f"{d}.geojson")


class PlanningDataExtra(PlanningData):
    """Các lớp planning.data.gov.uk bổ sung (di sản, môi trường, đất, quy hoạch). Lớp không có GeoJSON → lấy CSV (cột geometry/point WKT)."""

    name = "planning_data_extra"
    dataset_id = "uk.mhclg.planning_data_extra"
    description = ("planning.data.gov.uk bổ sung: scheduled monument, park & garden, battlefield, WHS, brownfield, đất ô nhiễm, "
                   "COMAH, heritage at risk, ancient woodland, AQMA, SAC/SPA/Ramsar, đơn xin cấp phép, local plan…")

    DATASETS = [
        "scheduled-monument", "park-and-garden", "battlefield", "world-heritage-site", "world-heritage-site-buffer-zone",
        "listed-building-outline", "locally-listed-building", "heritage-at-risk", "heritage-coast",
        "brownfield-land", "contaminated-land", "control-of-major-accident-hazards-site", "safety-hazard-area",
        "public-safety-zone-around-airport", "ancient-woodland", "air-quality-management-area",
        "special-area-of-conservation", "special-protection-area", "ramsar", "local-green-space", "open-space",
        "planning-application", "local-plan", "local-plan-boundary", "development-plan-boundary", "hs2-safeguarded-area",
    ]

    def plan(self, args):
        from email.utils import parsedate_to_datetime
        from common.http import probe
        self._files, lms, missing = [], [], []
        for d in self.DATASETS:
            for ext in ("geojson", "csv"):
                url = f"{PLANNING}/{d}.{ext}"
                if probe(url) in (200, 206):
                    self._files.append((url, f"{d}.{ext}"))
                    lm = head(url).headers.get("Last-Modified")
                    if lm:
                        lms.append(parsedate_to_datetime(lm).date())
                    break
            else:
                # vài lớp chưa có file tổng (chỉ có trong API theo entity): bỏ qua, ghi lại
                log.warning("  planning.data: chưa có file tải cho %s, bỏ qua", d)
                missing.append(d)
        if len(missing) > len(self.DATASETS) // 2:
            raise RuntimeError(f"planning.data: thiếu quá nhiều lớp: {missing}")
        v = max(lms) if lms else date.today()
        return self.release(v.isoformat(), period_end=v, meta={"files": [f for _, f in self._files], "missing": missing})

    def download(self, rel, args):
        for url, fname in self._files:
            rel.download(url, fname)


class ArcgisZones(Source):
    """Tải nhiều layer FeatureServer thành GeoJSON."""

    def __init__(self, name, dataset_id, layers: dict, description, workers=2, precision=6):
        self.name = name
        self.dataset_id = dataset_id
        self.layers = layers  # tên file → URL layer
        self.description = description
        self.workers = workers
        self.precision = precision

    def plan(self, args):
        return self.release(date.today().isoformat(), period_end=date.today(), meta={"layers": self.layers})

    def download(self, rel, args):
        for fname, url in self.layers.items():
            n = arcgis_export_geojson(url, rel.path(fname), page_size=2000, workers=self.workers,
                                      extra={"geometryPrecision": self.precision})
            rel.add_file(fname, url)
            rel.meta.setdefault("counts", {})[fname] = n


ZONE_SOURCES = [
    ArcgisZones("police_force_areas", "uk.ons.pfa", {
        "pfa.geojson": "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/Police_Force_Areas_Dec_2024_EW_BGC/FeatureServer/0",
    }, "ONS Police Force Areas (Dec 2024, BGC): xác định lực lượng cảnh sát của từng khu", workers=1, precision=6),
    ArcgisZones("natural_england", "uk.ne.designations", {
        "sssi.geojson": f"{NE}/SSSI_England/FeatureServer/0",
        "national_parks.geojson": f"{NE}/National_Parks_England/FeatureServer/0",
        "aonb.geojson": f"{NE}/Areas_of_Outstanding_Natural_Beauty_England/FeatureServer/0",
        "local_nature_reserves.geojson": f"{NE}/Local_Nature_Reserves_England/FeatureServer/0",
    }, "Natural England: SSSI, National Parks, National Landscapes (AONB), Local Nature Reserves (England)",
        workers=2, precision=6),
    ArcgisZones("ea_flood_zones", "uk.ea.flood_zones", {
        "flood_zone_3.geojson": f"{EA}/Flood_Map_for_Planning/FeatureServer/1",
        "flood_zone_2.geojson": f"{EA}/Flood_Map_for_Planning/FeatureServer/2",
        "flood_storage_areas.geojson": f"{EA}/Flood_Map_for_Planning/FeatureServer/0",
    }, "EA Flood Map for Planning (Rivers and Sea): Flood Zone 2, 3, flood storage areas (England)",
        workers=2, precision=5),
]
