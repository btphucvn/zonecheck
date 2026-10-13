"""Nhà đất: HM Land Registry Price Paid, UK HPI, ONS PIPR (giá thuê)."""
from __future__ import annotations

from datetime import date, datetime
from email.utils import parsedate_to_datetime

from common.http import head, probe
from common.sources import ons_latest_version

from .base import Source

PPD_BASE = "http://prod.publicdata.landregistry.gov.uk.s3-website-eu-west-1.amazonaws.com"


class PricePaid(Source):
    name = "ppd"
    dataset_id = "uk.land_registry.ppd"
    description = "HM Land Registry Price Paid Data (E&W, từ 1995). Mode: complete (~5 GB) | monthly | year"

    def add_arguments(self, p):
        p.add_argument("--mode", choices=["complete", "monthly", "year"], default="complete",
                       help="complete: toàn bộ lịch sử; monthly: file cập nhật tháng (thêm/sửa/xoá); year: một năm")
        p.add_argument("--year", type=int, default=date.today().year, help="dùng với --mode year")

    def plan(self, args):
        fname = {"complete": "pp-complete.csv", "monthly": "pp-monthly-update-new-version.csv",
                 "year": f"pp-{args.year}.csv"}[args.mode]
        self._url = f"{PPD_BASE}/{fname}"
        lm = head(self._url).headers.get("Last-Modified")
        published = parsedate_to_datetime(lm) if lm else datetime.now()
        label = args.mode if args.mode != "year" else f"year{args.year}"
        self._fname = fname
        return self.release(f"{label}-{published:%Y-%m-%d}", published_at=published,
                            meta={"mode": args.mode, "file": fname})

    def download(self, rel, args):
        rel.download(self._url, self._fname)


class UkHpi(Source):
    name = "uk_hpi"
    dataset_id = "uk.land_registry.hpi"
    description = "UK House Price Index full file (theo LA, hằng tháng)"

    def plan(self, args):
        today = date.today()
        for back in range(0, 8):
            y, m = divmod(today.year * 12 + today.month - 1 - back, 12)
            ym = f"{y}-{m + 1:02d}"
            url = f"https://publicdata.landregistry.gov.uk/market-trend-data/house-price-index-data/UK-HPI-full-file-{ym}.csv"
            if probe(url) in (200, 206):
                self._url = url
                return self.release(ym, meta={"file_month": ym})
        raise RuntimeError("Không tìm thấy file UK HPI trong 8 tháng gần nhất (mẫu .../UK-HPI-full-file-YYYY-MM.csv)")

    def download(self, rel, args):
        rel.download(self._url, self._url.rsplit("/", 1)[-1])


class OnsDataset(Source):
    """Dataset trên ons.gov.uk/.../datasets/<id>: tải mọi file của phiên bản mới nhất."""

    def __init__(self, name, dataset_id, page, description):
        self.name = name
        self.dataset_id = dataset_id
        self.page = page
        self.description = description

    def plan(self, args):
        v = ons_latest_version(self.page)
        self._files = v["files"]
        return self.release(v["version"], published_at=v["release_date"], meta={"uri": v["uri"]})

    def download(self, rel, args):
        for url in self._files:
            rel.download(url, url.rsplit("/", 1)[-1])


ONS_SOURCES = [
    OnsDataset("pipr", "uk.ons.pipr",
               "/economy/inflationandpriceindices/datasets/priceindexofprivaterentsukmonthlypricestatistics",
               "ONS Price Index of Private Rents: giá thuê theo LA × số phòng ngủ (hằng tháng)"),
    OnsDataset("ons_income_msoa", "uk.ons.income_msoa",
               "/employmentandlabourmarket/peopleinwork/earningsandworkinghours/datasets/"
               "smallareaincomeestimatesformiddlelayersuperoutputareasenglandandwales",
               "ONS small area income estimates theo MSOA (E&W)"),
]
