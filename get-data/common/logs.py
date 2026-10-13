"""Cấu hình log cho mọi tool cào dữ liệu.

- Màn hình: INFO trở lên, ngắn gọn.
- get-data/logs/<market>-YYYY-MM-DD.log : DEBUG trở lên (mọi request, retry, traceback đầy đủ).
- get-data/logs/<market>-errors.log     : chỉ ERROR, cộng dồn qua mọi lần chạy → xem nhanh lỗi gần đây.
Đổi thư mục log bằng ZC_LOG_DIR.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path

from .config import GET_DATA_DIR

FILE_FMT = "%(asctime)s %(levelname)-7s [%(process)d] %(name)s:%(lineno)d %(message)s"


def log_dir() -> Path:
    d = Path(os.environ.get("ZC_LOG_DIR") or GET_DATA_DIR / "logs")
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging(market: str) -> Path:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    root.addHandler(console)

    day_file = log_dir() / f"{market}-{date.today().isoformat()}.log"
    fh = logging.FileHandler(day_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(FILE_FMT))
    root.addHandler(fh)

    eh = logging.FileHandler(log_dir() / f"{market}-errors.log", encoding="utf-8")
    eh.setLevel(logging.ERROR)
    eh.setFormatter(logging.Formatter(FILE_FMT))
    root.addHandler(eh)

    # thư viện bên ngoài: chỉ giữ cảnh báo trở lên, riêng urllib3 giữ retry
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    return day_file
