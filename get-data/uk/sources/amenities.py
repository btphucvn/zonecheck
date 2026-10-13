"""Giao thông (NaPTAN), tiện ích (FSA, NHS ODS), môi trường (Defra PCM, EA flood areas)."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from common.http import get_json, probe

from .base import Source

log = logging.getLogger(__name__)


class Naptan(Source):
    name = "naptan"
    dataset_id = "uk.dft.naptan"
    description = "DfT NaPTAN: mọi điểm dừng xe buýt, ga tàu, tram, metro (GB, hằng ngày)"

    URL = "https://naptan.api.dft.gov.uk/v1/access-nodes?dataFormat=csv"

    def plan(self, args):
        return self.release(date.today().isoformat(), period_end=date.today())

    def download(self, rel, args):
        rel.download(self.URL, "naptan-stops.csv")


class Fsa(Source):
    name = "fsa"
    dataset_id = "uk.fsa.food_hygiene"
    description = "FSA Food Hygiene Rating: file XML của từng LA (UK, hằng ngày)"

    API = "https://api.ratings.food.gov.uk/Authorities"

    def plan(self, args):
        auths = get_json(self.API, headers={"x-api-version": "2", "accept": "application/json"})["authorities"]
        self._auths = auths
        latest = max(a["LastPublishedDate"] for a in auths)[:10]
        return self.release(latest, period_end=latest, meta={"authorities": len(auths)})

    def download(self, rel, args):
        rel.write_json("authorities.json", self._auths, self.API)
        jobs = []
        for a in self._auths:
            for key in ("FileName", "FileNameWelsh"):
                if a.get(key):
                    jobs.append(a[key])
        failures = []

        def one(url):
            try:
                rel.download(url, url.rsplit("/", 1)[-1])
            except Exception as e:
                log.error("  FSA: lỗi tải %s: %s: %s", url, type(e).__name__, e)
                failures.append((url, f"{type(e).__name__}: {e}"))

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(one, jobs))
        rel.files.sort(key=lambda f: f["path"])
        if failures:
            raise RuntimeError(f"FSA: {len(failures)}/{len(jobs)} file lỗi (chạy lại để tải tiếp phần thiếu): "
                               + "; ".join(f"{u} -> {e}" for u, e in failures[:20]))


class NhsOds(Source):
    name = "nhs_ods"
    dataset_id = "uk.nhs.ods"
    description = "NHS ODS: GP practice, nhà thuốc, nha khoa, cơ sở của NHS trust (England & Wales, hằng tuần)"

    REPORTS = {
        "epraccur": "GP practices",
        "edispensary": "pharmacies (dispensing contractors)",
        "egdpprac": "dental practices",
        "ets": "NHS trust sites (bệnh viện, phòng khám)",
    }

    def plan(self, args):
        return self.release(date.today().isoformat(), period_end=date.today(), meta={"reports": self.REPORTS})

    def download(self, rel, args):
        for r in self.REPORTS:
            rel.download(f"https://www.odsdatasearchandexport.nhs.uk/api/getReport?report={r}", f"{r}.csv")


class DefraPcm(Source):
    name = "defra_pcm"
    dataset_id = "uk.defra.pcm"
    description = "Defra PCM: nồng độ nền PM2.5, PM10, NO2 lưới 1 km (UK, hằng năm)"

    POLLUTANTS = {"pm25": "mappm25{y}g.csv", "pm10": "mappm10{y}g.csv", "no2": "mapno2{y}.csv"}
    BASE = "https://uk-air.defra.gov.uk/datastore/pcm"

    def add_arguments(self, p):
        p.add_argument("--year", type=int, help="năm dữ liệu; mặc định năm mới nhất có đủ file")

    def plan(self, args):
        years = [args.year] if args.year else range(date.today().year - 1, date.today().year - 6, -1)
        for y in years:
            urls = {k: f"{self.BASE}/{v.format(y=y)}" for k, v in self.POLLUTANTS.items()}
            codes = {k: probe(u) for k, u in urls.items()}
            log.debug("  PCM %s: %s", y, codes)
            ok = all(c in (200, 206) for c in codes.values())
            if ok:
                self._urls = urls
                return self.release(str(y), period_start=date(y, 1, 1), period_end=date(y, 12, 31))
        raise RuntimeError(f"Không tìm thấy bộ file PCM đầy đủ cho các năm {list(years)} tại {self.BASE} "
                           f"(mẫu tên: {list(self.POLLUTANTS.values())}) — có thể Defra đổi tên file")

    def download(self, rel, args):
        for url in self._urls.values():
            rel.download(url, url.rsplit("/", 1)[-1])


class EaFloodAreas(Source):
    name = "ea_flood_areas"
    dataset_id = "uk.ea.flood_areas"
    description = "EA Flood Monitoring: danh sách khu cảnh báo lũ (Flood Alert/Warning areas, England)"

    URL = "https://environment.data.gov.uk/flood-monitoring/id/floodAreas?_limit=10000"

    def plan(self, args):
        return self.release(date.today().isoformat(), period_end=date.today())

    def download(self, rel, args):
        d = get_json(self.URL, timeout=300)
        items = d.get("items", [])
        rel.row_count = len(items)
        if not 3_000 <= len(items) <= 6_000:
            raise RuntimeError(f"Số khu cảnh báo lũ bất thường: {len(items)}")
        rel.write_json("flood-areas.json", d, self.URL)
        # polygon từng khu (API trả GeoJSON riêng mỗi khu) → 2 file: Flood Warning (mã ...FW...) và Flood Alert
        from concurrent.futures import ThreadPoolExecutor

        import time

        def poly(it):
            time.sleep(0.5)  # tường lửa EA (Azure) chặn 403 khi gọi dồn dập
            g = get_json(it["polygon"].replace("http://", "https://"), timeout=120)
            feats = g.get("features") or []
            if not feats:
                raise RuntimeError(f"Khu {it['fwdCode']} không có polygon ({it['polygon']})")
            props = {k: it.get(k) for k in ("fwdCode", "label", "description", "county", "eaAreaName", "riverOrSea")}
            props["floodWatchArea"] = (it.get("floodWatchArea") or "").rsplit("/", 1)[-1] or None
            return [{"type": "Feature", "properties": props, "geometry": f["geometry"]} for f in feats]

        with ThreadPoolExecutor(max_workers=1) as ex:
            feats = [f for fs in ex.map(poly, items) for f in fs]
        out = {"warning": [], "alert": []}
        for f in feats:
            out["warning" if f["properties"]["fwdCode"][3:5] == "FW" else "alert"].append(f)
        for kind, fs in out.items():
            rel.write_json(f"flood_{kind}_areas.geojson", {"type": "FeatureCollection", "features": fs}, self.URL)
        rel.meta["counts"] = {k: len(v) for k, v in out.items()}
