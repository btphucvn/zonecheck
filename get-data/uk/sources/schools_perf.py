"""DfE Compare School Performance: kết quả KS2 / KS4 / KS5 theo trường (England), nhiều năm học."""
from __future__ import annotations

import logging
import re

from common.http import BROWSER_HEADERS, get_text

from .base import Source

log = logging.getLogger(__name__)

BASE = "https://www.compare-school-performance.service.gov.uk"


class DfePerformance(Source):
    name = "dfe_performance"
    dataset_id = "uk.dfe.school_performance"
    description = "DfE kết quả thi KS2/KS4/KS5 theo trường (CSV), mặc định 4 năm học gần nhất"

    def add_arguments(self, p):
        p.add_argument("--years", type=int, default=4, help="số năm học gần nhất cần tải (mặc định 4)")

    def plan(self, args):
        html = get_text(f"{BASE}/download-data", headers=BROWSER_HEADERS)
        years = re.findall(r'value="(\d{4}-\d{4})"', html)
        if not years:
            raise RuntimeError(f"Không đọc được danh sách năm học ở {BASE}/download-data (trang đổi giao diện?)")
        # bỏ năm học Covid (2019-2020 không có trong danh sách; 2020-2021 không có kết quả thi)
        years = [y for y in years if y != "2020-2021"][: args.years]
        self._years = years
        return self.release(years[0], meta={"years": years})

    def download(self, rel, args):
        from common.http import HttpError
        got = []
        for i, y in enumerate(self._years):
            for ks in ("KS2", "KS4", "KS5"):
                url = f"{BASE}/download-data?download=true&regions=0&filters={ks}&fileformat=csv&year={y}&meta=false"
                try:
                    # tải một KS → server trả thẳng CSV (không phải zip)
                    path = rel.download(url, f"dfe-{ks.lower()}-{y}.csv", headers=BROWSER_HEADERS)
                    head = path.open("rb").read(64).decode("utf-8-sig", "replace")
                    if not head.startswith("RECTYPE"):
                        raise RuntimeError(f"{path.name} không phải CSV DfE (bắt đầu bằng {head[:40]!r})")
                    got.append(f"{ks}/{y}")
                except HttpError as e:
                    if i == 0 or e.response is None or e.response.status_code != 404:
                        raise  # năm mới nhất bắt buộc phải có; lỗi khác 404 → dừng
                    log.warning("  DfE không có %s năm %s (404) → bỏ qua", ks, y)
        y = self._years[0]
        rel.download(f"{BASE}/download-data?download=true&regions=KS2,KS4,KS5&filters=meta&fileformat=csv&year={y}&meta=true",
                     f"dfe-meta-{y}.zip", headers=BROWSER_HEADERS)
        rel.meta["downloaded"] = got


class DfeSchoolProfile(Source):
    """Hồ sơ trường từ cùng trang DfE: học sinh (census), vắng học, nơi học sinh đi tiếp, số bài thi theo môn.

    Mỗi loại dữ liệu lấy năm học mới nhất có file (destinations thường trễ hơn kết quả thi một năm).
    """
    name = "dfe_school_profile"
    dataset_id = "uk.dfe.school_profile"
    description = "DfE theo trường: học sinh (giới, SEN, EAL, FSM), vắng học, destinations KS4/16-18/HE, số bài thi KS4 theo môn"
    # filter DfE → tiền tố file; bắt đầu file phải khớp (CSV) hoặc là zip
    FILTERS = {
        "CENSUS": ("census", "URN,"),
        "PUPILABSENCE": ("absence", "LA,"),
        "KS4DESTINATION": ("ks4dest", "RECTYPE,"),
        "KS5DESTINATION": ("ks5dest", "RECTYPE,"),
        "KS5DESTINATIONHE": ("ks5desthe", "RECTYPE,"),
        "KS4UNDERLYING": ("ks4subjects", None),
    }

    def plan(self, args):
        html = get_text(f"{BASE}/download-data", headers=BROWSER_HEADERS)
        years = [y for y in re.findall(r'value="(\d{4}-\d{4})"', html) if y != "2020-2021"]
        if not years:
            raise RuntimeError(f"Không đọc được danh sách năm học ở {BASE}/download-data (trang đổi giao diện?)")
        self._years = years[:3]
        return self.release(years[0], meta={"years": self._years})

    def download(self, rel, args):
        from common.http import HttpError
        got = {}
        for flt, (prefix, head_re) in self.FILTERS.items():
            for y in self._years:
                url = f"{BASE}/download-data?download=true&regions=0&filters={flt}&fileformat=csv&year={y}&meta=false"
                ext = "zip" if head_re is None else "csv"
                try:
                    path = rel.download(url, f"dfe-{prefix}-{y}.{ext}", headers=BROWSER_HEADERS)
                except HttpError as e:
                    if e.response is not None and e.response.status_code in (400, 404):
                        log.info("  DfE chưa có %s năm %s (%s) → thử năm trước", flt, y, e.response.status_code)
                        continue
                    raise
                head = path.open("rb").read(64)
                ok = head.startswith(b"PK") if head_re is None else head.decode("utf-8-sig", "replace").startswith(head_re)
                if not ok:
                    path.unlink()
                    rel.files[:] = [f for f in rel.files if f["path"] != path.name]
                    log.info("  %s năm %s không phải dữ liệu (bắt đầu %r) → thử năm trước", flt, y, head[:30])
                    continue
                got[flt] = y
                break
            else:
                raise RuntimeError(f"DfE: không tải được {flt} cho các năm {self._years}")
        rel.meta["downloaded"] = got
