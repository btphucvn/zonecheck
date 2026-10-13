"""ORR Estimates of station usage (Table 1410): lượt vào/ra, trung chuyển, mã ga 3 chữ (CRS/TLC)."""
from __future__ import annotations

import re

from common.http import BROWSER_HEADERS, get_text

from .base import Source

ORR = "https://dataportal.orr.gov.uk"


class OrrStationUsage(Source):
    name = "orr_station_usage"
    dataset_id = "uk.orr.station_usage"
    description = "ORR station usage (Table 1410 CSV, năm tài chính mới nhất): lượt vào/ra, trung chuyển, mã CRS"

    def plan(self, args):
        html = get_text(f"{ORR}/statistics/usage/estimates-of-station-usage/", headers=BROWSER_HEADERS)
        links = re.findall(r'href="(/media/[^"]+table-1410-passenger-entries-and-exits-and-interchanges-by-station\.csv)"', html)
        if not links:
            raise RuntimeError("Không thấy file Table 1410 CSV trên trang ORR (giao diện đổi?)")
        self._url = ORR + links[0]
        head = get_text(self._url, headers=BROWSER_HEADERS)[:400]
        m = re.search(r"April (\d{4}) to March (\d{4})", head)
        if not m:
            raise RuntimeError(f"Không đọc được kỳ dữ liệu từ tiêu đề ORR: {head[:200]!r}")
        return self.release(f"{m.group(1)}-{m.group(2)[2:]}", period_end=f"{m.group(2)}-03-31",
                            meta={"title": head.split(",")[0].strip('"')})

    def download(self, rel, args):
        rel.download(self._url, "table-1410-station-usage.csv", headers=BROWSER_HEADERS)
