"""Council tax: mức thuế theo band (England MHCLG Table 9, Wales Table 1) + phân bố band theo khu (VOA CTSOP1.1)."""
from __future__ import annotations

import logging
import re
from datetime import date

from common.http import BROWSER_HEADERS, get_json, get_text

from .base import Source

log = logging.getLogger(__name__)


def _fy(start: int) -> str:
    return f"{start}-{str(start + 1)[2:]}"


def _govuk_attachment(path: str, title_re: str) -> str | None:
    try:
        d = get_json(f"https://www.gov.uk/api/content{path}")
    except Exception as e:  # trang chưa có (404) → thử năm trước
        log.debug("  %s: %s", path, e)
        return None
    for a in d.get("details", {}).get("attachments", []):
        if re.search(title_re, a.get("title", ""), re.I) and str(a.get("url", "")).startswith("https://"):
            return a["url"]
    return None


class CouncilTax(Source):
    name = "council_tax"
    dataset_id = "uk.council_tax"
    description = "Council tax: mức thuế band A–H/I theo LA (England + Wales, năm tài chính mới nhất) + số nhà theo band (VOA, tới LSOA)"

    def plan(self, args):
        today = date.today()
        start = today.year if today.month >= 3 else today.year - 1  # mức năm sau công bố khoảng tháng 3
        for y in (start, start - 1):
            eng = _govuk_attachment(
                f"/government/statistics/council-tax-levels-set-by-local-authorities-in-england-{y}-to-{y + 1}",
                r"Tables 1 to 9")
            if eng:
                break
        else:
            raise RuntimeError("Không tìm thấy Council Tax levels England (Tables 1 to 9) cho năm hiện tại/trước")
        fy = _fy(y)
        html = get_text(f"https://www.gov.wales/council-tax-levels-april-{y}-march-{y + 1}", headers=BROWSER_HEADERS)
        wales = re.findall(r'https://www\.gov\.wales/sites/default/files/[^"\s]+\.xlsx', html)
        if not wales:
            raise RuntimeError(f"Không thấy file council tax Wales {fy}")
        for sy in (today.year, today.year - 1):
            ctsop = _govuk_attachment(f"/government/statistics/council-tax-stock-of-properties-{sy}", r"^CTSOP1\.1")
            if ctsop:
                break
        else:
            raise RuntimeError("Không tìm thấy VOA CTSOP1.1")
        self._files = {"england_tables_1_9.ods": eng, "wales_levels.xlsx": wales[0], "ctsop1_1.zip": ctsop}
        return self.release(fy, period_start=date(y, 4, 1), period_end=date(y + 1, 3, 31),
                            meta={"financial_year": fy, "ctsop_year": sy, **self._files})

    def download(self, rel, args):
        for fname, url in self._files.items():
            rel.download(url, fname, headers=BROWSER_HEADERS if "gov.wales" in url else None)
