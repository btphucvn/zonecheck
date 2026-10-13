"""Cấu hình chung cho các tool cào dữ liệu.

Thứ tự đọc biến môi trường (biến đã có trong môi trường luôn được ưu tiên):
  1. get-data/.env              (dùng trên VPS, chứa DATABASE_URL trỏ 127.0.0.1:5432)
  2. auth_key/vps/vps.env       (dùng ở máy local, DATABASE_URL đi qua SSH tunnel)
"""
from __future__ import annotations

import os
from pathlib import Path

GET_DATA_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = GET_DATA_DIR.parent


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_env_file(GET_DATA_DIR / ".env")
_load_env_file(REPO_DIR / "auth_key" / "vps" / "vps.env")


def data_root(market: str) -> Path:
    """Thư mục lưu dữ liệu thô của một market. Mặc định get-data/<market>/data, đổi bằng ZC_DATA_DIR."""
    base = os.environ.get("ZC_DATA_DIR")
    root = Path(base) / market if base else GET_DATA_DIR / market / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def database_url() -> str | None:
    return os.environ.get("DATABASE_URL")


USER_AGENT = os.environ.get(
    "ZC_USER_AGENT", "Mozilla/5.0 (compatible; ZoneCheckDataBot/0.1; open-data ETL)"
)
