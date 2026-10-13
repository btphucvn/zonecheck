"""Nguồn bổ sung để lấp khoảng trống so với đối thủ (xem DATA_GAP_TRACKER.md):
y tế (CQC), nhà trẻ (Ofsted childcare), an toàn giao thông (STATS19, AADF), London (PTAL, TfL), OSM, khí hậu
(HadUK-Grid), hành chính (MP), tribunal nhà đất, LHA, fly-tipping, thống kê ONS, trường (applications & offers).
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import date, datetime
from email.utils import parsedate_to_datetime

from common.http import BROWSER_HEADERS, SESSION, get_json, get_text, head
from common.sources import filename_from_url, govuk_attachments

from .base import Source
from .environment import CkanFiles
from .housing import OnsDataset
from .social import Census2021
from .zones import ArcgisZones

MO = "https://services.arcgis.com/Lq3V5RFuTBC9I7kv/arcgis/rest/services"

log = logging.getLogger(__name__)


def last_modified(url: str, headers: dict | None = None) -> date:
    """Last-Modified qua HEAD; server không cho HEAD (405) thì GET 1 byte."""
    try:
        lm = head(url, headers=headers).headers.get("Last-Modified")
    except Exception:  # noqa: BLE001
        r = SESSION.get(url, headers={**(headers or {}), "Range": "bytes=0-0"}, stream=True, timeout=60)
        r.close()
        if r.status_code >= 400:
            raise RuntimeError(f"GET {url} → HTTP {r.status_code}")
        lm = r.headers.get("Last-Modified")
    return parsedate_to_datetime(lm).date() if lm else date.today()


# ------------------------------------------------------------------- y tế -----
class Cqc(Source):
    name = "cqc"
    dataset_id = "uk.cqc.directory"
    description = "CQC: danh bạ cơ sở (GP, bệnh viện, nha khoa, nhà dưỡng lão…) + xếp hạng mới nhất (England)"
    PAGE = "https://www.cqc.org.uk/about-us/transparency/using-cqc-data"
    WANT = {"directory": r"CQC_directory\.csv$", "ratings": r"Latest_ratings\.ods$", "locations": r"HSCA_Active_Locations\.ods$"}

    def plan(self, args):
        html = get_text(self.PAGE, headers=BROWSER_HEADERS)
        links = re.findall(r'href="(https://www\.cqc\.org\.uk/[^"]+\.(?:csv|ods|zip))"', html)
        self._urls = []
        for kind, pat in self.WANT.items():
            hits = [u for u in links if re.search(pat, u)]
            if not hits:
                raise RuntimeError(f"Không thấy file CQC {kind} ({pat}) trên {self.PAGE}")
            self._urls.append(hits[0])
        m = re.search(r"/(\d{1,2})_([A-Za-z]+)_(\d{4})_CQC_directory", self._urls[0])
        v = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date() if m else date.today()
        return self.release(v.isoformat(), period_end=v, meta={"files": [filename_from_url(u) for u in self._urls]})

    def download(self, rel, args):
        for u in self._urls:
            rel.download(u, filename_from_url(u), headers=BROWSER_HEADERS)


class GovukLatestStats(Source):
    """Trang thống kê gov.uk phát hành theo kỳ (tiêu đề đổi theo ngày): tìm bản mới nhất qua search API rồi tải đính kèm."""

    def __init__(self, name, dataset_id, query, title_re, include, description, doc_format=None):
        self.name = name
        self.dataset_id = dataset_id
        self.query = query
        self.title_re = title_re
        self.include = include
        self.description = description
        self.doc_format = doc_format

    def plan(self, args):
        params = {"q": self.query, "count": 40, "fields": "title,link,public_timestamp,format"}
        if self.doc_format:
            params["filter_format"] = self.doc_format
        res = get_json("https://www.gov.uk/api/search.json", params=params)["results"]
        hits = [r for r in res if re.search(self.title_re, r["title"], re.I)]
        if not hits:
            raise RuntimeError(f"gov.uk search {self.query!r}: không tiêu đề nào khớp {self.title_re!r}. "
                               f"Có: {[r['title'] for r in res][:10]}")
        # trang cũ đôi khi được sửa lại nên public_timestamp mới → ưu tiên năm lớn nhất trong tiêu đề
        page = max(hits, key=lambda r: (max(map(int, re.findall(r"\b(?:19|20)\d\d\b", r["title"])), default=0),
                                        r.get("public_timestamp", "")))
        pat = re.compile(self.include, re.I)
        self._atts = [a for a in govuk_attachments(page["link"]) if pat.search(a["url"])]
        if not self._atts:
            raise RuntimeError(f"{page['link']}: không file nào khớp {self.include!r}")
        v = page.get("public_timestamp", "")[:10] or date.today().isoformat()
        return self.release(v, published_at=page.get("public_timestamp"), meta={"page": page["link"], "title": page["title"]})

    def download(self, rel, args):
        for a in self._atts:
            rel.download(a["url"], filename_from_url(a["url"]))


# --------------------------------------------------------------- giao thông ---
class UrlFiles(Source):
    """Danh sách URL cố định; phiên bản = Last-Modified mới nhất."""

    def __init__(self, name, dataset_id, urls: list[str], description, headers=None):
        self.name = name
        self.dataset_id = dataset_id
        self.urls = urls
        self.description = description
        self.headers = headers

    def plan(self, args):
        v = max(last_modified(u, self.headers) for u in self.urls)
        return self.release(v.isoformat(), period_end=v, meta={"urls": self.urls})

    def download(self, rel, args):
        for u in self.urls:
            rel.download(u, filename_from_url(u), headers=self.headers)


DFT = "https://data.dft.gov.uk/road-accidents-safety-data"


class TflStations(Source):
    name = "tfl_stations"
    dataset_id = "uk.tfl.stations"
    description = "TfL Unified API: ga tube/DLR/Overground/Elizabeth line/tram kèm travel zone và tuyến"
    MODES = ["tube", "dlr", "overground", "elizabeth-line", "tram"]

    def plan(self, args):
        return self.release(date.today().isoformat(), period_end=date.today(), meta={"modes": self.MODES})

    def download(self, rel, args):
        total = 0
        for m in self.MODES:
            d = get_json(f"https://api.tfl.gov.uk/StopPoint/Mode/{m}", timeout=300)
            pts = d.get("stopPoints", [])
            if not pts:
                raise RuntimeError(f"TfL {m}: không có stopPoint")
            total += len(pts)
            rel.write_json(f"stoppoints_{m}.json", d, url=f"https://api.tfl.gov.uk/StopPoint/Mode/{m}")
        rel.row_count = total


# Khí hậu: CEDA (dap.ceda.ac.uk) đòi đăng nhập → dùng Met Office Climate Data Portal (ArcGIS) ở EXTRA_SOURCES.


# ----------------------------------------------------------------- OSM --------
class OsmUk(Source):
    name = "osm_uk"
    dataset_id = "uk.osm.geofabrik"
    description = "OpenStreetMap UK (Geofabrik .osm.pbf, ~2 GB): pub, café, gym, bể bơi, thư viện, trạm sạc EV, đường điện cao thế…"
    URL = "https://download.geofabrik.de/europe/united-kingdom-latest.osm.pbf"

    def plan(self, args):
        v = last_modified(self.URL)
        return self.release(v.isoformat(), period_end=v, meta={"url": self.URL, "licence": "ODbL"})

    def download(self, rel, args):
        md5 = get_text(self.URL + ".md5").split()[0]
        rel.download(self.URL, "united-kingdom-latest.osm.pbf", expect_md5=md5)


# --------------------------------------------------------------- hành chính ---
class ParliamentMps(Source):
    name = "parliament_mps"
    dataset_id = "uk.parliament.mps"
    description = "UK Parliament Members API: MP đương nhiệm (House of Commons) kèm khu bầu cử, đảng"
    API = "https://members-api.parliament.uk/api/Members/Search"

    def plan(self, args):
        return self.release(date.today().isoformat(), period_end=date.today())

    def download(self, rel, args):
        items, skip = [], 0
        while True:
            d = get_json(self.API, params={"House": 1, "IsCurrentMember": "true", "skip": skip, "take": 20})
            page = d.get("items", [])
            items += [x.get("value", x) for x in page]
            skip += len(page)
            if not page or skip >= d.get("totalResults", 0):
                break
        if not 600 <= len(items) <= 660:
            raise RuntimeError(f"Số MP bất thường: {len(items)} (kỳ vọng ~650)")
        rel.write_json("mps.json", items, url=self.API)
        rel.row_count = len(items)


class TribunalDecisions(Source):
    name = "tribunal_decisions"
    dataset_id = "uk.govuk.rpt_decisions"
    description = "gov.uk Residential Property Tribunal decisions: địa chỉ/postcode, loại vụ, ngày (England)"
    API = "https://www.gov.uk/api/search.json"
    FIELDS = "title,link,public_timestamp,description,tribunal_decision_category,tribunal_decision_sub_category"

    def plan(self, args):
        return self.release(date.today().isoformat(), period_end=date.today())

    def download(self, rel, args):
        base = {"filter_format": "residential_property_tribunal_decision", "fields": self.FIELDS,
                "order": "-public_timestamp"}
        total = get_json(self.API, params={**base, "count": 0})["total"]
        out, start = [], 0
        while start < total:
            d = get_json(self.API, params={**base, "count": 1000, "start": start}, timeout=300)
            res = d.get("results", [])
            if not res:
                break
            out += res
            start += len(res)
        if len(out) < 0.98 * total:
            raise RuntimeError(f"Tribunal: nhận {len(out)}/{total}")
        rel.write_json("rpt_decisions.json", out, url=self.API)
        rel.row_count = len(out)


# --------------------------------------------------------- trường học (EES) ---
class EesReleaseFiles(Source):
    """Tải zip 'all files' của release mới nhất chứa data set có tiêu đề khớp regex (Explore Education Statistics)."""

    API = "https://content.explore-education-statistics.service.gov.uk/api"

    def __init__(self, name, dataset_id, search, title_re, description):
        self.name = name
        self.dataset_id = dataset_id
        self.search = search
        self.title_re = title_re
        self.description = description

    def plan(self, args):
        d = get_json(f"{self.API}/data-set-files", params={"searchTerm": self.search, "pageSize": 40, "latestOnly": "true"})
        hits = [r for r in d.get("results", []) if re.search(self.title_re, r.get("title", ""), re.I)]
        if not hits:
            raise RuntimeError(f"EES: không data set nào khớp {self.title_re!r}: {[r.get('title') for r in d.get('results', [])]}")
        r = hits[0]
        self._release = r["release"]["id"]
        rel_title = r["release"].get("title") or r["release"].get("slug") or self._release
        return self.release(re.sub(r"[^\w.-]+", "-", str(rel_title)).strip("-"),
                            published_at=r.get("published"), meta={"release_id": self._release, "data_set": r.get("title")})

    def download(self, rel, args):
        rel.download(f"{self.API}/releases/{self._release}/files", f"ees_{self._release}.zip", headers=BROWSER_HEADERS)


class Census2021Extra(Census2021):
    name = "census2021_extra"
    description = "Census 2021 bảng bổ sung: nơi sinh, thời gian cư trú, khả năng tiếng Anh, khuyết tật, chăm sóc không lương, nghề nghiệp"
    DEFAULT = ["ts004", "ts016", "ts029", "ts038", "ts039", "ts063"]

    def plan(self, args):
        rel = super().plan(args)
        if rel.version == "2021":
            rel = self.release("2021-extra", meta=rel.meta)
        return rel


EXTRA_SOURCES = [
    Cqc(),
    GovukLatestStats("ofsted_childcare", "uk.ofsted.childcare",
                     "childcare providers and inspections as at", r"^Childcare providers and inspections as at \d",
                     r"(provider_level|inspection).*\.(ods|csv|xlsx)$",
                     "Ofsted: nhà trẻ, người giữ trẻ (provider level) + kết quả thanh tra (England)",
                     doc_format="official_statistics"),
    UrlFiles("dft_stats19", "uk.dft.stats19", [
        f"{DFT}/dft-road-casualty-statistics-collision-last-5-years.csv",
        f"{DFT}/dft-road-casualty-statistics-casualty-last-5-years.csv",
        f"{DFT}/dft-road-casualty-statistics-vehicle-last-5-years.csv",
    ], "DfT STATS19: tai nạn giao thông có thương vong, 5 năm gần nhất (toạ độ, mức độ, người đi bộ/xe đạp) GB"),
    UrlFiles("dft_traffic", "uk.dft.traffic_aadf", [
        "https://storage.googleapis.com/dft-statistics/road-traffic/downloads/data-gov-uk/dft_traffic_counts_aadf.zip",
    ], "DfT road traffic: lưu lượng xe trung bình ngày (AADF) theo điểm đếm, theo năm (GB)"),
    CkanFiles("london_ptal", "uk.gla.ptal", {
        "public-transport-accessibility-levels1": r"(Grid%20Values\.zip|LSOA2011%20AvPTAI2015\.csv|COA2011%20AvPTAI2015\.csv)$",
    }, "London Datastore: PTAL 2015 (lưới 100 m + trung bình theo OA/LSOA 2011)", min_files=3),
    TflStations(),
    ArcgisZones("haduk_grid", "uk.metoffice.haduk_grid", {
        f"{svc.lower()}.geojson": f"{MO}/{svc}/FeatureServer/{lid}"
        for svc, lid in [("Annual_Temperature_Observations_1991_2020", 2), ("Annual_Max_Temperature_Observations_1991_2020", 9),
                         ("Annual_Min_Temperature_Observations_1991_2020", 7), ("Annual_Precipitation_Observations_1991_2020", 0),
                         ("Annual_Count_of_Airfrost_Days_1991_2020", 0), ("Annual_Count_of_Summer_Days_1991_2020", 0),
                         ("Annual_Count_of_10mm_Rain_Days_1991_2020", 0), ("Annual_Count_of_Icing_Days_1991_2020", 0)]
    }, "Met Office Climate Data Portal (HadUK-Grid): trung bình 1991–2020 nhiệt độ, mưa, ngày sương giá/hè/mưa lớn (lưới, UK)",
        workers=2, precision=5),
    OsmUk(),
    ParliamentMps(),
    TribunalDecisions(),
    GovukLatestStats("lha_rates", "uk.voa.lha_rates", "local housing allowance rates applicable from april",
                     r"^Local Housing Allowance \(LHA\) rates applicable from April \d{4}", r"\.(csv|xlsx|ods|zip)$",
                     "VOA Local Housing Allowance: mức trần trợ cấp thuê nhà theo BRMA × số phòng (năm hiện hành)"),
    GovukLatestStats("fly_tipping", "uk.defra.fly_tipping", "fly-tipping statistics for england",
                     r"^Fly-tipping statistics for England$", r"\.(csv|xlsx|ods)$",
                     "Defra fly-tipping: số vụ vứt rác trái phép theo LA × loại, các năm (England)",
                     doc_format="official_statistics"),
    OnsDataset("ons_affordability", "uk.ons.affordability",
               "/peoplepopulationandcommunity/housing/datasets/ratioofhousepricetoworkplacebasedearningslowerquartileandmedian",
               "ONS tỷ lệ giá nhà / thu nhập (trung vị, nhóm thấp) theo LA, các năm"),
    OnsDataset("ons_lsoa_population", "uk.ons.lsoa_population",
               "/peoplepopulationandcommunity/populationandmigration/populationestimates/datasets/lowersuperoutputareamidyearpopulationestimates",
               "ONS dân số giữa năm theo LSOA 2021 × tuổi × giới (E&W)"),
    Census2021Extra(),
    EesReleaseFiles("dfe_school_offers", "uk.dfe.school_offers", "applications and offers",
                    r"^Secondary and primary schools? applications and offers \d{4}$",
                    "DfE applications & offers: số đơn, tỷ lệ nguyện vọng 1 (LA + file cấp trường nếu có), England"),
]
