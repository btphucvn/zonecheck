"""Wales: WIMD 2025 (mức thiếu thốn theo LSOA) và danh sách trường của Welsh Government."""
from __future__ import annotations

import re

from common.http import BROWSER_HEADERS, get_text

from .base import Source

GOV_WALES = "https://www.gov.wales"


def _page_files(page: str, pattern: str) -> list[str]:
    html = get_text(f"{GOV_WALES}{page}", headers=BROWSER_HEADERS)
    urls = sorted(set(re.findall(r'https://www\.gov\.wales/sites/default/files/[^"\s]+', html)))
    hits = [u for u in urls if re.search(pattern, u)]
    if not hits:
        raise RuntimeError(f"Không thấy file khớp {pattern!r} ở {GOV_WALES}{page} (có {len(urls)} file: {urls[:8]})")
    return hits


class Wimd(Source):
    name = "wimd"
    dataset_id = "uk.welsh_gov.wimd"
    description = "Welsh Index of Multiple Deprivation 2025: điểm + hạng theo LSOA 2021 (8 lĩnh vực)"

    PAGE = "/welsh-index-multiple-deprivation-2025"

    def plan(self, args):
        self._files = _page_files(self.PAGE, r"wimd-2025-index-and-domain-(ranks|scores)-by-small-area\.ods$")
        if len(self._files) != 2:
            raise RuntimeError(f"WIMD: cần đúng 2 file (ranks, scores), thấy {self._files}")
        return self.release("2025", meta={"files": self._files})

    def download(self, rel, args):
        for u in self._files:
            rel.download(u, u.rsplit("/", 1)[-1], headers=BROWSER_HEADERS)


class WalesSchools(Source):
    name = "wales_schools"
    dataset_id = "uk.welsh_gov.schools"
    description = "Danh sách trường Wales (maintained, independent, PRU): cấp học, ngôn ngữ, quản lý, sĩ số"

    PAGE = "/addresses-and-phone-numbers-schools-and-pupil-referral-units"

    def plan(self, args):
        files = _page_files(self.PAGE, r"address-list-schools.*\.ods$")
        self._url = files[0]
        m = re.search(r"/(\d{4}-\d{2})/", self._url)
        return self.release(m.group(1) if m else "latest", meta={"url": self._url})

    def download(self, rel, args):
        rel.download(self._url, "address-list-schools.ods", headers=BROWSER_HEADERS)
