"""Nguồn chặn client tự động (Cloudflare): file được tải bằng Chrome thật (uk/manual/fetch.py, chạy ở máy local)
vào uk/manual/<thư mục>/, rsync lên VPS, rồi các tool dưới đây chép vào release như mọi nguồn khác.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .base import Source

MANUAL = Path(__file__).resolve().parent.parent / "manual"


class ManualSource(Source):
    folder: str = ""
    patterns: dict[str, str] = {}  # loại file → regex tên file, nhóm 1 = kỳ dữ liệu (so sánh được dạng chuỗi)

    def plan(self, args):
        d = MANUAL / self.folder
        files = sorted(p for p in d.glob("*") if p.is_file()) if d.is_dir() else []
        newest = {}
        for kind, pat in self.patterns.items():
            hits = [(m.group(1), p) for p in files if (m := re.fullmatch(pat, p.name))]
            if not hits:
                raise RuntimeError(f"Chưa có file {kind} ({pat}) trong {d}. Chạy uk/manual/fetch.py ở máy local "
                                   f"rồi rsync uk/manual/ lên VPS (xem uk/manual/README.md)")
            newest[kind] = max(hits)
        periods = {p for p, _ in newest.values()}
        if len(periods) != 1:
            raise RuntimeError(f"Các file {self.name} không cùng kỳ dữ liệu: { {k: v[0] for k, v in newest.items()} }")
        self._files = [p for _, p in newest.values()]
        return self.release(self.version_label(periods.pop()), meta={"files": [p.name for p in self._files]})

    def version_label(self, period: str) -> str:
        return period

    def download(self, rel, args):
        for p in self._files:
            shutil.copy2(p, rel.path(p.name))
            rel.add_file(p.name, url=f"manual:{self.folder}/{p.name}")


class OfcomConnectedNations(ManualSource):
    name = "ofcom_connected_nations"
    dataset_id = "uk.ofcom.connected_nations"
    description = "Ofcom Connected Nations: phủ sóng broadband theo OA + phủ sóng di động theo LA (tải tay)"
    folder = "ofcom"
    patterns = {"fixed": r"(\d{6})_fixed_broadband_coverage.*\.zip", "mobile": r"(\d{6})_mobile_coverage.*\.zip"}

    def version_label(self, period):
        return f"{period[:4]}-{period[4:]}"


class NhsGpPatients(ManualSource):
    name = "nhs_gp_patients"
    dataset_id = "uk.nhs.gp_patients"
    description = "NHS England: số bệnh nhân đăng ký theo GP practice (tháng mới nhất, tải tay)"
    folder = "nhs_gp_patients"
    patterns = {"totals": r"gp-reg-pat-prac-all-(\d{4}-\d{2})\.zip"}
