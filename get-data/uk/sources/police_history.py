"""Lịch sử tội phạm từ 12/2010: số vụ theo LSOA 2021 × năm × loại (chỉ tổng hợp, không lưu từng vụ).

Tải khoảng 8 GB archive: chạy trên VPS (mạng nhanh, ~20 MB/s) với ZC_WORKERS=1, hoặc ở máy local nhiều nhân nếu mạng nhanh.

- Archive data.police.uk `archive/YYYY-MM.zip` chứa 36 tháng tới YYYY-MM. Dùng các archive 2013-11, 2016-11, 2019-11,
  2022-11, 2023-08 (phủ 12/2010–08/2023; từ 09/2023 đã có trong mkt_uk.crime_incident). Mỗi tháng lấy từ archive
  MỚI NHẤT có chứa tháng đó (bản police đã sửa sau cùng).
- Mã LSOA trong file cũ là 2011, file mới là 2021. Mã 2011 → 2021 theo bảng Exact Fit của ONS: LSOA bị tách (S)
  chia đều số vụ cho các LSOA 2021 con; gộp (M) và không đổi (U) giữ nguyên.
- Ghi: crime_lsoa_year.csv.gz (lsoa21, year, crime_type, n) và force_months.csv (force, month) để biết lực lượng
  nào thiếu tháng nào (Greater Manchester ngừng gửi dữ liệu từ 07/2019).
- File zip được xoá sau khi dựng xong; manifest chỉ giữ hai file kết quả + bảng lookup.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import os
import re
import zipfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

from common.sources import arcgis_export_geojson

from .base import Source

log = logging.getLogger(__name__)

ARCHIVES = ["2013-11", "2016-11", "2019-11", "2022-11", "2023-08"]
LAST_MONTH = "2023-08"  # từ 2023-09 dùng mkt_uk.crime_incident
LOOKUP = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/LSOA11_LSOA21_LAD22_EW_LU_v5/FeatureServer/0"


def months_back(end: str, n: int = 36) -> list[str]:
    y, m = map(int, end.split("-"))
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def owner_of_months() -> dict[str, str]:
    """tháng → archive mới nhất chứa tháng đó (≤ LAST_MONTH)."""
    own = {}
    for a in sorted(ARCHIVES):
        for m in months_back(a):
            if m <= LAST_MONTH:
                own[m] = a
    return own


def _scan(args) -> tuple[dict, set, dict]:
    """Đọc một archive: (lsoa, year, type) → số vụ cho các tháng archive này sở hữu; tập (force, month) có file;
    (lsoa, month) → số vụ (để đo độ phủ theo tháng)."""
    path, months = args
    counts: dict[tuple[str, int, str], int] = defaultdict(int)
    by_month: dict[tuple[str, str], int] = defaultdict(int)
    forces: set[tuple[str, str]] = set()
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            m = re.match(r"(?:.*/)?(\d{4}-\d{2})/\1-(.+)-street\.csv$", name)
            if not m or m.group(1) not in months:
                continue
            month, force = m.group(1), m.group(2)
            forces.add((force, month))
            year = int(month[:4])
            with zf.open(name) as fh:
                for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")):
                    code = (r.get("LSOA code") or "").strip()
                    if code[:1] in ("E", "W"):
                        counts[(code, year, r.get("Crime type") or "")] += 1
                        by_month[(code, month)] += 1
    return dict(counts), forces, dict(by_month)


class PoliceHistory(Source):
    name = "police_history"
    dataset_id = "uk.police.history"
    description = "Lịch sử tội phạm 12/2010–08/2023 theo LSOA 2021 × năm × loại (tổng hợp từ archive, chạy local)"

    def plan(self, args):
        return self.release(LAST_MONTH, period_start=date(2010, 12, 1), period_end=date(2023, 8, 31),
                            meta={"archives": ARCHIVES})

    def download(self, rel, args):
        # bảng lookup LSOA 2011 → 2021
        lk = rel.path("lsoa11_lsoa21.geojson")
        n_lk = arcgis_export_geojson(LOOKUP, lk, out_fields="ObjectId,LSOA11CD,LSOA21CD,CHGIND,LAD22CD", extra={"returnGeometry": "false"})
        rel.add_file(lk.name, LOOKUP)
        children: dict[str, list[str]] = defaultdict(list)
        lad_of: dict[str, str] = {}
        for f in json.loads(lk.read_text())["features"]:
            p = f["properties"]
            children[p["LSOA11CD"]].append(p["LSOA21CD"])
            lad_of[p["LSOA11CD"]] = lad_of[p["LSOA21CD"]] = p["LAD22CD"]
        lsoa21 = {c for cs in children.values() for c in cs}
        log.info("  lookup: %s dòng, %s LSOA 2011, %s LSOA 2021", n_lk, len(children), len(lsoa21))

        own = owner_of_months()
        jobs = []
        for a in ARCHIVES:
            dest = rel.path(f"{a}.zip")
            if not dest.exists():
                rel.download(f"https://data.police.uk/data/archive/{a}.zip", dest.name)
            jobs.append((str(dest), {m for m, o in own.items() if o == a}))
        total: dict[tuple[str, int, str], float] = defaultdict(float)
        forces: set[tuple[str, str]] = set()
        lad_month: dict[tuple[str, str], int] = defaultdict(int)
        unknown = 0
        # ZC_WORKERS: số tiến trình đọc archive (VPS 2 nhân: đặt 1 để chừa CPU cho Postgres)
        workers = int(os.environ.get("ZC_WORKERS") or min(len(jobs), os.cpu_count() or 2))
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for (counts, fm, bm), (path, months) in zip(ex.map(_scan, jobs), jobs):
                log.info("  %s: %s tháng, %s ô (LSOA×năm×loại), %s file lực lượng", Path(path).name, len(months), len(counts), len(fm))
                forces |= fm
                for (code, month), n in bm.items():
                    if code in lad_of:
                        lad_month[(lad_of[code], month)] += n
                for (code, year, ctype), n in counts.items():
                    if code in lsoa21:
                        total[(code, year, ctype)] += n
                    elif code in children:
                        kids = children[code]
                        for k in kids:
                            total[(k, year, ctype)] += n / len(kids)
                    else:
                        unknown += n
        n_all = sum(total.values())
        log.info("  tổng %s vụ, %s vụ có mã LSOA không nhận ra (%.2f%%)", f"{n_all:,.0f}", f"{unknown:,}", 100 * unknown / max(n_all, 1))
        if unknown > 0.01 * n_all:
            raise RuntimeError(f"Quá nhiều mã LSOA không khớp: {unknown:,}")
        out = rel.path("crime_lsoa_year.csv.gz")
        with gzip.open(out, "wt", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["lsoa21", "year", "crime_type", "n"])
            for (code, year, ctype), n in sorted(total.items()):
                w.writerow([code, year, ctype, round(n, 3)])
        rel.add_file(out.name, "https://data.police.uk/data/archive/")
        fm = rel.path("force_months.csv")
        with open(fm, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["force", "month"])
            w.writerows(sorted(forces))
        rel.add_file(fm.name, "https://data.police.uk/data/archive/")
        lm = rel.path("lad_months.csv")
        with open(lm, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["lad22", "month", "n"])
            w.writerows(sorted((lad, m, n) for (lad, m), n in lad_month.items()))
        rel.add_file(lm.name, "https://data.police.uk/data/archive/")
        # xoá archive gốc (khoảng 8 GB), chỉ giữ kết quả tổng hợp
        for a in ARCHIVES:
            rel.path(f"{a}.zip").unlink(missing_ok=True)
        rel.files[:] = [f for f in rel.files if not f["path"].endswith(".zip")]
        rel.row_count = len(total)
