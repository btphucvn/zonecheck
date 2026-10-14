"""Phân loại khu dân cư: UK Output Area Classification 2021/22 (GeoDS cùng ONS, OGL).

- Bảng OA → supergroup/group/subgroup: `data/UK_OAC_Final.parquet` trong repo GitHub chính thức của GeoDS
  (GeographicDataService/Output_Area_Classification). Trang tải trên data.geods.ac.uk cần đăng nhập.
- Tên và mô tả (pen portrait): API của ứng dụng tra cứu GeoDS (apps.geods.ac.uk/oac). Mỗi lần tra trả về đủ
  21 group; tên supergroup lấy bằng một postcode đại diện cho mỗi supergroup (OA đầu tiên của supergroup đó).
"""
from __future__ import annotations

import json
import logging
from datetime import date

from common import db
from common.http import BROWSER_HEADERS, get_json

from .base import Source

log = logging.getLogger(__name__)

REPO = "https://raw.githubusercontent.com/GeographicDataService/Output_Area_Classification/HEAD"
APP = "https://apps.geods.ac.uk/oac/OACSearch/PostCodeSearch"


class GeodsOac(Source):
    name = "geods_oac"
    dataset_id = "uk.geods.oac2021"
    description = "UK Output Area Classification 2021/22 (GeoDS/ONS): OA → supergroup/group/subgroup + tên và mô tả"

    def plan(self, args):
        return self.release(date.today().isoformat(), period_end=date(2022, 3, 20), meta={"repo": REPO, "app": APP})

    def download(self, rel, args):
        import pyarrow.parquet as pq
        path = rel.download(f"{REPO}/data/UK_OAC_Final.parquet", "UK_OAC_Final.parquet")
        rows = pq.read_table(path).to_pylist()
        if not 230_000 <= len(rows) <= 250_000:
            raise RuntimeError(f"UK_OAC_Final.parquet có {len(rows):,} OA (kỳ vọng ~239 nghìn)")
        first = {}
        for r in rows:
            if r["Geography_Code"][:1] in ("E", "W"):
                first.setdefault(r["Supergroup"], r["Geography_Code"])
        labels = {"supergroups": {}, "groups": {}}
        conn = db.conn()
        if conn is None:
            raise RuntimeError("Cần DB (mkt_uk.postcode) để chọn postcode đại diện cho mỗi supergroup")
        for sg, oa in sorted(first.items()):
            pc = conn.execute("SELECT postcode FROM mkt_uk.postcode WHERE oa21_code = %s AND status = 'live' LIMIT 1", (oa,)).fetchone()
            if not pc:
                raise RuntimeError(f"Không có postcode cho OA {oa} (supergroup {sg})")
            d = get_json(APP, params={"postCode": pc[0]}, headers={**BROWSER_HEADERS, "X-Requested-With": "XMLHttpRequest"})
            g = d["oacSupergroupGroup"]
            if g["supergroupCode"] != sg:
                raise RuntimeError(f"Postcode {pc[0]} (OA {oa}) trả supergroup {g['supergroupCode']}, kỳ vọng {sg}")
            labels["supergroups"][sg] = {"name": g["supergroupName"], "pen_portrait": g["supergroupPenPortrait"]}
            for x in d["oacGroupCodeNamePenPortraits"]:
                labels["groups"][x["groupCode"]] = {"name": x["groupName"], "pen_portrait": x["groupPenPortrait"]}
        if len(labels["supergroups"]) != 8 or len(labels["groups"]) != 21:
            raise RuntimeError(f"Thiếu nhãn: {len(labels['supergroups'])} supergroup, {len(labels['groups'])} group")
        p = rel.path("oac_labels.json")
        p.write_text(json.dumps(labels, ensure_ascii=False, indent=1))
        rel.add_file("oac_labels.json", APP)
        rel.row_count = len(rows)
