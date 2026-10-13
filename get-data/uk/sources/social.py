"""Tội phạm (data.police.uk), trường học (GIAS, Ofsted), IoD 2025, Census 2021 (Nomis)."""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from common.http import get_json, get_text, probe
from common.sources import filename_from_url, govuk_attachments, parse_day_month_year

from .base import Source

log = logging.getLogger(__name__)


class Police(Source):
    name = "police"
    dataset_id = "uk.police.street_crime"
    description = "data.police.uk archive tháng (street crime + outcomes + stop&search, 36 tháng gần nhất, E&W + NI)"

    def add_arguments(self, p):
        p.add_argument("--month", help="YYYY-MM; mặc định tháng mới nhất")

    def plan(self, args):
        dates = get_json("https://data.police.uk/api/crimes-street-dates")
        self._dates = dates
        available = sorted(d["date"] for d in dates)
        month = args.month or available[-1]
        if month not in available:
            raise ValueError(f"Tháng {month} không có trên data.police.uk (có {available[0]} → {available[-1]})")
        y, m = map(int, month.split("-"))
        start_y, start_m = divmod(y * 12 + m - 1 - 35, 12)
        return self.release(month, period_start=date(start_y, start_m + 1, 1), period_end=date(y, m, 1),
                            meta={"archive_covers_months": 36})

    def download(self, rel, args):
        # danh sách lực lượng có dữ liệu theo tháng → phát hiện khoảng trống (mkt_uk.crime_coverage_gap)
        rel.write_json("crimes-street-dates.json", self._dates, "https://data.police.uk/api/crimes-street-dates")
        rel.write_json("forces.json", get_json("https://data.police.uk/api/forces"), "https://data.police.uk/api/forces")
        rel.download(f"https://data.police.uk/data/archive/{rel.version}.zip", f"police-archive-{rel.version}.zip")


class Gias(Source):
    name = "gias"
    dataset_id = "uk.dfe.gias"
    description = "DfE Get Information About Schools: toàn bộ cơ sở giáo dục England (+ links), cập nhật hằng ngày"

    BASE = "https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/public"

    def plan(self, args):
        for back in range(0, 10):
            d = date.today() - timedelta(days=back)
            url = f"{self.BASE}/edubasealldata{d:%Y%m%d}.csv"
            if probe(url) in (200, 206):
                self._d = d
                return self.release(d.isoformat(), period_end=d)
        raise RuntimeError(f"Không tìm thấy file GIAS trong 10 ngày gần nhất (mẫu {self.BASE}/edubasealldataYYYYMMDD.csv)")

    def download(self, rel, args):
        d = f"{self._d:%Y%m%d}"
        rel.download(f"{self.BASE}/edubasealldata{d}.csv", f"edubasealldata{d}.csv")
        rel.download(f"{self.BASE}/links_edubasealldata{d}.csv", f"links_edubasealldata{d}.csv")


class Ofsted(Source):
    name = "ofsted"
    dataset_id = "uk.ofsted.schools_mi"
    description = ("Ofsted management information trường state-funded: lần thanh tra mới nhất + mọi lần trong năm "
                   "(cả mô hình cũ và report card từ 11/2025)")

    PAGE = "/government/statistical-data-sets/monthly-management-information-ofsteds-school-inspections-outcomes"

    def plan(self, args):
        atts = [a for a in govuk_attachments(self.PAGE) if a.get("content_type") == "text/csv"]
        latest = {}
        for a in atts:
            t = a.get("title", "")
            if "state-funded schools" not in t:
                continue
            kind = "latest" if "latest inspections" in t else "ytd" if "year to date" in t else None
            d = parse_day_month_year(t)
            if kind and d and (kind not in latest or d > latest[kind][0]):
                latest[kind] = (d, a)
        if "latest" not in latest:
            titles = [a.get("title") for a in atts][-10:]
            raise RuntimeError(f"Không tìm thấy file Ofsted 'latest inspections' ở {self.PAGE}. "
                               f"{len(atts)} file CSV, 10 tiêu đề cuối: {titles}")
        d = latest["latest"][0]
        self._atts = [a for k, (dd, a) in latest.items() if dd == d or k == "latest"]
        return self.release(d.date().isoformat(), period_end=d.date(),
                            meta={"titles": [a["title"] for a in self._atts]})

    def download(self, rel, args):
        for a in self._atts:
            rel.download(a["url"], filename_from_url(a["url"]))


class GovukAttachments(Source):
    """Tải file đính kèm (lọc theo regex trên URL) từ một trang gov.uk."""

    def __init__(self, name, dataset_id, page, version, description, include=r"\.(csv|xlsx|ods|zip)$",
                 all_include=None):
        self.name = name
        self.dataset_id = dataset_id
        self.page = page
        self.version = version
        self.description = description
        self.include = include
        self.all_include = all_include

    def add_arguments(self, p):
        if self.all_include:
            p.add_argument("--all-files", action="store_true", help="tải mọi file thay vì bộ mặc định")

    def plan(self, args):
        pat = re.compile(self.all_include if getattr(args, "all_files", False) and self.all_include else self.include)
        self._atts = [a for a in govuk_attachments(self.page) if pat.search(a["url"])]
        if not self._atts:
            raise RuntimeError(f"Không có file khớp {pat.pattern} ở {self.page}")
        return self.release(self.version, meta={"page": self.page, "files": len(self._atts)})

    def download(self, rel, args):
        for a in self._atts:
            rel.download(a["url"], filename_from_url(a["url"]))


GOVUK_SOURCES = [
    GovukAttachments(
        "transport_connectivity", "uk.dft.connectivity", "/government/publications/transport-connectivity-metric",
        "2025", "DfT Transport connectivity metric 2025: điểm kết nối 0–100 theo OA/LSOA (đi bộ, xe đạp, công cộng, ô tô)",
        include=r"connectivity_metrics.*\.ods$",
    ),
    GovukAttachments(
        "iod2025", "uk.mhclg.iod2025", "/government/statistics/english-indices-of-deprivation-2025", "2025",
        "English Indices of Deprivation 2025 theo LSOA (mặc định File 7 CSV; --all-files để lấy mọi bảng)",
        include=r"File_7_.*\.csv$", all_include=r"\.(csv|xlsx)$",
    ),
    GovukAttachments(
        "journey_time", "uk.dft.journey_time", "/government/statistical-data-sets/journey-time-statistics-data-tables-jts",
        "2019", "DfT Journey Time Statistics: thời gian tới dịch vụ thiết yếu theo LSOA (bảng JTS05xx)",
        include=r"jts05\d\d\.(ods|xlsx|csv)$", all_include=r"jts\d{4}\.(ods|xlsx|csv)$",
    ),
]


class Census2021(Source):
    name = "census2021"
    dataset_id = "uk.ons.census2021"
    description = "Census 2021 bulk (Nomis) theo OA/LSOA/MSOA/LAD. Mặc định các bảng TS dùng cho báo cáo khu vực"

    # Bảng dùng cho trang khu vực. Dân tộc/tôn giáo chỉ để mô tả, không đưa vào điểm số (PLAN mục 7).
    DEFAULT = [
        "ts001",  # dân số thường trú
        "ts003",  # cấu trúc hộ
        "ts006",  # mật độ dân số
        "ts007a",  # nhóm tuổi
        "ts011",  # số chiều thiếu thốn của hộ
        "ts017",  # quy mô hộ
        "ts021",  # dân tộc (mô tả)
        "ts030",  # tôn giáo (mô tả)
        "ts037",  # sức khoẻ
        "ts041",  # số hộ
        "ts044",  # loại nhà
        "ts045",  # số ô tô
        "ts046",  # sưởi trung tâm
        "ts050",  # số phòng ngủ
        "ts054",  # sở hữu / thuê
        "ts058",  # quãng đường đi làm
        "ts061",  # phương tiện đi làm
        "ts062",  # NS-SeC
        "ts066",  # tình trạng kinh tế
        "ts067",  # trình độ học vấn
    ]

    def add_arguments(self, p):
        p.add_argument("--tables", help="danh sách bảng, ví dụ ts001,ts054 (mặc định bộ chọn sẵn)")
        p.add_argument("--all-tables", action="store_true", help="tải toàn bộ bảng TS")

    def plan(self, args):
        html = get_text("https://www.nomisweb.co.uk/sources/census_2021_bulk")
        available = sorted(set(re.findall(r"census2021-(ts\d+[a-z]?)\.zip", html)))
        if args.all_tables:
            wanted = available
        else:
            wanted = args.tables.split(",") if args.tables else self.DEFAULT
            missing = [t for t in wanted if t not in available]
            if missing:
                log.warning("  Nomis không có bảng: %s", ", ".join(missing))
            wanted = [t for t in wanted if t in available]
        self._tables = wanted
        version = "2021-all" if args.all_tables else "2021-" + "-".join(wanted) if args.tables else "2021"
        return self.release(version, meta={"tables": wanted})

    def download(self, rel, args):
        for t in self._tables:
            rel.download(f"https://www.nomisweb.co.uk/output/census/2021/census2021-{t}.zip", f"census2021-{t}.zip")
