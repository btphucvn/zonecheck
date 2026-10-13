"""EPC nhà ở (England & Wales) từ dịch vụ MHCLG mới (get-energy-performance-data.communities.gov.uk).

Cần EPC_API_KEY (bearer token, lấy ở trang tài khoản sau khi đăng nhập GOV.UK One Login), đặt trong .env / vps.env.
Bản bulk là zip các file CSV theo năm, tạo lại ngày 1 hằng tháng.
"""
from __future__ import annotations

import os
from datetime import datetime

from common.http import get_json

from .base import Source

API = "https://api.get-energy-performance-data.communities.gov.uk"


def _headers() -> dict:
    key = os.environ.get("EPC_API_KEY")
    if not key:
        raise RuntimeError("Thiếu EPC_API_KEY (đặt trong get-data/.env hoặc auth_key/vps/vps.env)")
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


class EpcDomestic(Source):
    name = "epc"
    dataset_id = "uk.mhclg.epc_domestic"
    description = "EPC nhà ở E&W (bulk CSV theo năm, ~8 GB zip): hạng năng lượng, diện tích sàn, số phòng, sưởi, UPRN"

    def plan(self, args):
        info = get_json(f"{API}/api/files/domestic/csv/info", headers=_headers())["data"]
        updated = datetime.fromisoformat(info["lastUpdated"].replace("Z", "+00:00"))
        self._size = info.get("fileSize")
        return self.release(updated.date().isoformat(), published_at=updated,
                            meta={"file_size": self._size, "last_updated": info["lastUpdated"]})

    def download(self, rel, args):
        # API trả 302 sang URL S3 ký sẵn; requests tự bỏ header Authorization khi chuyển sang host khác
        path = rel.download(f"{API}/api/files/domestic/csv", "epc-domestic-csv.zip", headers=_headers())
        if self._size and path.stat().st_size != self._size:
            raise RuntimeError(f"EPC zip {path.stat().st_size} bytes, API báo {self._size} bytes")
