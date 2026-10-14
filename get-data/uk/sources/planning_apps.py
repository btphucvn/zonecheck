"""London Planning Datahub (GLA): đơn xin cấp phép quy hoạch của 35 cơ quan quy hoạch London, 3 năm gần nhất.

API Elasticsearch cho khách (header X-API-AllowRequest công khai trong tài liệu GLA). Phân trang search_after theo id,
chỉ lấy các trường cần cho trang khu vực. Ghi JSONL nén.
"""
from __future__ import annotations

import gzip
import json
import logging
from datetime import date, timedelta

from common.http import SESSION

from .base import Source

log = logging.getLogger(__name__)

API = "https://planningdata.london.gov.uk/api-guest/applications/_search"
HEADERS = {"Content-Type": "application/json", "X-API-AllowRequest": "be2rmRnt&"}
FIELDS = ["id", "lpa_name", "lpa_app_no", "site_name", "site_number", "street_name", "postcode", "description",
          "application_type", "application_type_full", "development_type", "status", "decision", "decision_date",
          "valid_date", "url_planning_app", "centroid_easting", "centroid_northing", "ward"]
YEARS = 3


class LondonPlanning(Source):
    name = "london_planning"
    dataset_id = "uk.gla.planning_datahub"
    description = "London Planning Datahub: đơn xin cấp phép quy hoạch 3 năm gần nhất (London), có toạ độ"

    def plan(self, args):
        return self.release(date.today().isoformat(), period_start=date.today() - timedelta(days=365 * YEARS),
                            period_end=date.today())

    def download(self, rel, args):
        since = (date.today() - timedelta(days=365 * YEARS)).strftime("%d/%m/%Y")
        q = {"size": 5000, "_source": FIELDS, "sort": [{"id": "asc"}],
             "query": {"range": {"valid_date": {"gte": since, "format": "dd/MM/yyyy"}}}}
        out = rel.path("london_planning.jsonl.gz")
        n, after = 0, None
        with gzip.open(out, "wt") as fh:
            while True:
                body = dict(q, search_after=after) if after else q
                r = SESSION.post(API, headers=HEADERS, data=json.dumps(body), timeout=120)
                r.raise_for_status()
                hits = r.json()["hits"]["hits"]
                if not hits:
                    break
                for h in hits:
                    fh.write(json.dumps(h["_source"], ensure_ascii=False) + "\n")
                n += len(hits)
                after = hits[-1]["sort"]
                if n % 50000 < 5000:
                    log.info("  %s hồ sơ", f"{n:,}")
        if n < 100_000:
            raise RuntimeError(f"Chỉ tải được {n:,} hồ sơ (kỳ vọng vài trăm nghìn trong {YEARS} năm)")
        rel.add_file(out.name, API)
        rel.row_count = n
