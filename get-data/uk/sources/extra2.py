"""Nguồn bổ sung đợt 2 (DATA_GAP_TRACKER.md): GP Patient Survey, HM Land Registry (công ty sở hữu nhà, hợp đồng
thuê dài hạn) và DWP Stat-Xplore (người nhận Universal Credit theo LSOA).

HMLR cần HMLR_API_KEY và phải ký licence từng dataset trên use-land-property-data.service.gov.uk.
Stat-Xplore cần STATXPLORE_API_KEY. Cả hai key đọc từ get-data/.env hoặc auth_key/vps/vps.env.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import re
import time
import urllib.parse
from datetime import date

from common import db
from common.http import BROWSER_HEADERS, SESSION, get_json, get_text

from .base import Source

log = logging.getLogger(__name__)


# -------------------------------------------------------- GP Patient Survey -----
class GpPatientSurvey(Source):
    name = "gp_patient_survey"
    dataset_id = "uk.nhs.gpps"
    description = "GP Patient Survey (Ipsos/NHS England): kết quả theo từng phòng khám GP (CSV có trọng số, England)"
    SITE = "https://www.gp-patient.co.uk"
    PAGE = f"{SITE}/latest-survey/results"
    # file CSV practice-level nằm sau /FileDownload/Download?fileRedirect=<năm>/survey-results/practice-results/...
    LINK = r'href="(/FileDownload/Download\?fileRedirect=(\d{4})%2Fsurvey-results%2Fpractice-results%2Fpractice-data-csv%2F[^"]+\.csv)"'

    def plan(self, args):
        html = get_text(self.PAGE, headers=BROWSER_HEADERS)
        m = re.search(self.LINK, html)
        if not m:
            raise RuntimeError(f"Không thấy link CSV practice-level trên {self.PAGE} (trang đổi cấu trúc?)")
        self._url = self.SITE + m.group(1).replace("&amp;", "&")
        year = int(m.group(2))
        # thực địa tháng 1–4, công bố tháng 7
        return self.release(str(year), period_start=date(year, 1, 1), period_end=date(year, 4, 30),
                            meta={"url": self._url, "page": self.PAGE})

    def download(self, rel, args):
        fname = urllib.parse.unquote(self._url.rsplit("%2F", 1)[-1])
        path = rel.download(self._url, fname, headers=BROWSER_HEADERS)
        with open(path, encoding="utf-8-sig", newline="") as f:
            r = csv.reader(f)
            header = next(r)
            n = sum(1 for _ in r)
        need = {"ad_practicecode", "overallexp.pcteval", "localgpservicesphone.pcteval"}
        if not need <= set(header):
            raise RuntimeError(f"GPPS CSV thiếu cột {need - set(header)}")
        if not 5000 <= n <= 7500:
            raise RuntimeError(f"Số phòng khám GPPS bất thường: {n} (~6.200)")
        rel.row_count = n


# --------------------------------------------------------- HM Land Registry -----
HMLR_API = "https://use-land-property-data.service.gov.uk/api/v1"


def hmlr_get(path: str) -> dict:
    key = os.environ.get("HMLR_API_KEY")
    if not key:
        raise RuntimeError("Thiếu HMLR_API_KEY (get-data/.env hoặc auth_key/vps/vps.env)")
    r = SESSION.get(f"{HMLR_API}/{path}", headers={"Authorization": key, "Accept": "application/json"}, timeout=60)
    try:
        d = r.json()
    except ValueError:
        raise RuntimeError(f"HMLR {path}: HTTP {r.status_code}, phản hồi không phải JSON: {r.text[:300]!r}") from None
    if r.status_code != 200 or not d.get("success", True):
        err = d.get("error") or d
        hint = ""
        if "not yet signed the licence" in str(err):
            hint = " → đăng nhập use-land-property-data.service.gov.uk, mở dataset và bấm đồng ý licence"
        elif "do not have access" in str(err):
            hint = " → dataset cần xin quyền truy cập (Registered Leases là freemium) trên use-land-property-data.service.gov.uk"
        raise RuntimeError(f"HMLR {path}: HTTP {r.status_code}: {err}{hint}")
    return d


class HmlrDataset(Source):
    """Bộ dữ liệu trên Use land and property data: lấy file Full mới nhất qua API (link S3 có hạn)."""

    def __init__(self, name, dataset_id, api_name, description):
        self.name = name
        self.dataset_id = dataset_id
        self.api_name = api_name
        self.description = description

    def plan(self, args):
        res = hmlr_get(f"datasets/{self.api_name}")["result"]
        full = [x for x in res.get("resources", []) if re.match(rf"{self.api_name.upper()}_FULL_\d{{4}}_\d{{2}}\.zip$",
                                                                  x.get("file_name", ""), re.I)]
        if len(full) != 1:
            raise RuntimeError(f"HMLR {self.api_name}: cần đúng 1 file FULL, thấy {[x.get('file_name') for x in res.get('resources', [])]}")
        self._file = full[0]["file_name"]
        y, m = map(int, re.search(r"_(\d{4})_(\d{2})\.zip$", self._file).groups())
        return self.release(f"{y}-{m:02d}", period_end=date(y, m, 1),
                            meta={"file": self._file, "rows": full[0].get("row_count"), "size": full[0].get("file_size"),
                                  "last_updated": res.get("last_updated")})

    def download(self, rel, args):
        d = hmlr_get(f"datasets/{self.api_name}/{self._file}")
        url = d["result"]["download_url"]  # link S3 ký sẵn, hết hạn sau vài phút → tải ngay
        rel.download(url, self._file)
        rel.files[-1]["url"] = f"{HMLR_API}/datasets/{self.api_name}/{self._file}"  # không lưu link có chữ ký
        rel.row_count = rel.meta.get("rows")


# ------------------------------------------------------- DWP Stat-Xplore -----
SX_API = "https://stat-xplore.dwp.gov.uk/webapi/rest/v1"
UC_DB = "str:database:UC_Monthly"
UC_COUNT = "str:count:UC_Monthly:V_F_UC_CASELOAD_FULL"
UC_DATE = "str:field:UC_Monthly:F_UC_DATE:DATE_NAME"
UC_GEO = "str:field:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE"
UC_LSOA = "str:value:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE:V_C_MASTERGEOG21_LSOA_TO_MSOA"
UC_EMP = "str:field:UC_Monthly:V_F_UC_CASELOAD_FULL:EMPLOYMENT_CODE"
UC_EMP_V = "str:value:UC_Monthly:V_F_UC_CASELOAD_FULL:EMPLOYMENT_CODE:C_UC_EMPLOYMENT_2023_BAND"
EMP_BANDS = {"0": "not_working", "1": "working", "99": "unknown"}


def sx_post_table(body: dict) -> dict:
    key = os.environ.get("STATXPLORE_API_KEY")
    if not key:
        raise RuntimeError("Thiếu STATXPLORE_API_KEY (get-data/.env hoặc auth_key/vps/vps.env)")
    last = None
    for attempt in range(5):
        r = SESSION.post(f"{SX_API}/table", json=body, headers={"APIKey": key, "Accept-Encoding": "gzip"}, timeout=600)
        if r.status_code == 200:
            return r.json()
        last = f"HTTP {r.status_code}: {r.text[:500]!r}"
        log.warning("  Stat-Xplore lần %s lỗi: %s", attempt + 1, last)
        if r.status_code in (400, 401, 403, 404, 422):  # lỗi truy vấn/key: thử lại vô ích
            break
        # 429: vượt hạn mức (200 bảng/giờ) → nghỉ lâu
        time.sleep(300 if r.status_code == 429 else 20 * (attempt + 1))
    raise RuntimeError(f"Stat-Xplore /table thất bại: {last}\nbody: {json.dumps(body)[:800]}")


class DwpUniversalCredit(Source):
    name = "dwp_uc"
    dataset_id = "uk.dwp.uc_people"
    description = "DWP Stat-Xplore: người nhận Universal Credit theo LSOA 2021 × có/không có việc làm, tháng mới nhất (GB)"
    CHUNK = 4000  # số LSOA mỗi bảng (Stat-Xplore giới hạn số ô mỗi truy vấn)

    def plan(self, args):
        # tổng GB theo tháng × có/không việc làm; tháng mới nhất thường chưa có chỉ báo việc làm (toàn "Not available")
        # → lấy tháng mới nhất đã tách được việc làm
        d = sx_post_table({"database": UC_DB, "measures": [UC_COUNT],
                           "recodes": {UC_EMP: {"map": [[f"{UC_EMP_V}:{k}"] for k in EMP_BANDS], "total": False}},
                           "dimensions": [[UC_DATE], [UC_EMP]]})
        items = d["fields"][0]["items"]
        bands = [i["uris"][0].rsplit(":", 1)[-1] for i in d["fields"][1]["items"]]
        vals = next(iter(d["cubes"].values()))["values"]
        ok = [(i["uris"][0], dict(zip(bands, v))) for i, v in zip(items, vals)
              if sum(v) and (dict(zip(bands, v)).get("99", 0) or 0) < 0.2 * sum(v)]
        if not ok:
            raise RuntimeError("Không có tháng nào tách được người có/không việc làm")
        self._month_uri, by_band = ok[-1]
        self._gb_total = sum(by_band.values())
        ym = self._month_uri.rsplit(":", 1)[-1]
        if not re.fullmatch(r"\d{6}", ym):
            raise RuntimeError(f"Mã tháng lạ: {self._month_uri}")
        y, m = int(ym[:4]), int(ym[4:])
        return self.release(f"{y}-{m:02d}", period_end=date(y, m, 1),
                            meta={"gb_total": self._gb_total, "gb_by_band": by_band,
                                  "latest_month": items[-1]["uris"][0].rsplit(":", 1)[-1]})

    def lsoa_codes(self) -> list[str]:
        c = db.conn()
        if c is None:
            raise RuntimeError("Cần DB (core.geo_area) để lấy danh sách LSOA 2021")
        return [r[0] for r in c.execute("SELECT code FROM core.geo_area WHERE market_code='uk' AND level_code='lsoa' ORDER BY code")]

    def download(self, rel, args):
        codes = self.lsoa_codes()
        if not 35_000 <= len(codes) <= 36_500:
            raise RuntimeError(f"Số LSOA bất thường: {len(codes)}")
        out = rel.path("uc_people_lsoa.csv")
        total = 0
        with open(out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["lsoa21", "employment", "people"])
            for i in range(0, len(codes), self.CHUNK):
                part = codes[i:i + self.CHUNK]
                d = sx_post_table({
                    "database": UC_DB, "measures": [UC_COUNT],
                    "recodes": {
                        UC_DATE: {"map": [[self._month_uri]], "total": False},
                        UC_GEO: {"map": [[f"{UC_LSOA}:{c}"] for c in part], "total": False},
                        UC_EMP: {"map": [[f"{UC_EMP_V}:{k}"] for k in EMP_BANDS], "total": False},
                    },
                    "dimensions": [[UC_GEO], [UC_EMP], [UC_DATE]]})
                geo_items = d["fields"][0]["items"]
                emp_items = d["fields"][1]["items"]
                cube = next(iter(d["cubes"].values()))["values"]
                for gi, row in zip(geo_items, cube):
                    code = gi["uris"][0].rsplit(":", 1)[-1]
                    for ei, cell in zip(emp_items, row):
                        v = cell[0]  # chiều tháng chỉ có 1 giá trị
                        band = EMP_BANDS[ei["uris"][0].rsplit(":", 1)[-1]]
                        w.writerow([code, band, v])
                        total += v or 0
                log.info("  %s/%s LSOA", min(i + self.CHUNK, len(codes)), len(codes))
        # E&W chiếm ~90% số người nhận UC của GB (Scotland không có LSOA)
        share = total / self._gb_total
        log.info("  tổng E&W %s / GB %s (%.1f%%)", f"{total:,.0f}", f"{self._gb_total:,}", share * 100)
        if not 0.85 <= share <= 0.95:
            raise RuntimeError(f"Tổng UC theo LSOA E&W = {share:.1%} tổng GB, ngoài [85%, 95%]")
        rel.add_file(out.name, url=f"{SX_API}/table ({UC_DB})")
        rel.meta["ew_total"] = total
        rel.row_count = len(codes)


EXTRA2_SOURCES = [
    GpPatientSurvey(),
    HmlrDataset("hmlr_ccod", "uk.land_registry.ccod", "ccod",
                "HM Land Registry CCOD: nhà đất England & Wales do công ty UK sở hữu (full file, hằng tháng)"),
    HmlrDataset("hmlr_ocod", "uk.land_registry.ocod", "ocod",
                "HM Land Registry OCOD: nhà đất England & Wales do công ty nước ngoài sở hữu (full file, hằng tháng)"),
    HmlrDataset("hmlr_leases", "uk.land_registry.leases", "leases",
                "HM Land Registry Registered Leases: hợp đồng thuê dài hạn đã đăng ký (ngày, thời hạn) — cần xin quyền"),
    DwpUniversalCredit(),
]
