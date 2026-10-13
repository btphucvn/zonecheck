"""Một "release" = một lần tải một phiên bản của dataset vào thư mục riêng:

    <data_root>/<source>/<version>/
        <các file gốc>
        manifest.json      # ghi khi tải xong: danh sách file, sha256, url, thời điểm

Có manifest.json nghĩa là bản đó đã tải đủ → lần sau bỏ qua (trừ khi --force).
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

from . import db
from .config import data_root
from .http import download, sha256_file

log = logging.getLogger(__name__)


class Release:
    def __init__(self, market: str, source: str, dataset_id: str, version: str,
                 period_start: date | str | None = None, period_end: date | str | None = None,
                 published_at: datetime | str | None = None, meta: dict | None = None):
        self.market = market
        self.source = source
        self.dataset_id = dataset_id
        self.version = version
        self.period_start = period_start
        self.period_end = period_end
        self.published_at = published_at
        self.meta = dict(meta or {})
        self.dir = data_root(market) / source / version
        self.files: list[dict] = []
        self.row_count: int | None = None

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    def is_complete(self) -> bool:
        return self.manifest_path.is_file()

    def reset(self) -> None:
        if self.dir.exists():
            shutil.rmtree(self.dir)

    def path(self, filename: str) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        return self.dir / filename

    def download(self, url: str, filename: str, headers: dict | None = None, expect_md5: str | None = None) -> Path:
        dest = self.path(filename)
        if dest.exists() and not dest.with_name(dest.name + ".part").exists():
            log.info("  đã có %s, bỏ qua tải", filename)
            info = {"path": filename, "url": url, "bytes": dest.stat().st_size, "sha256": sha256_file(dest)}
        else:
            log.info("  tải %s", url)
            info = download(url, dest, headers=headers)
        if expect_md5:
            h = hashlib.md5()
            with open(dest, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            md5 = h.hexdigest()
            if md5.lower() != expect_md5.lower():
                dest.unlink()
                raise ValueError(f"MD5 không khớp cho {filename}: {md5} != {expect_md5}")
        self.files.append(info)
        return dest

    def add_file(self, filename: str, url: str | None = None) -> Path:
        """Ghi nhận file do code tự sinh ra (ví dụ GeoJSON ghép từ nhiều trang API)."""
        dest = self.dir / filename
        self.files.append({"path": filename, "url": url, "bytes": dest.stat().st_size, "sha256": sha256_file(dest)})
        return dest

    def write_json(self, filename: str, obj, url: str | None = None) -> Path:
        dest = self.path(filename)
        dest.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
        return self.add_file(filename, url)

    def finish(self) -> dict:
        if not self.files:
            raise RuntimeError("release không có file nào")
        combined = hashlib.sha256(
            "\n".join(f"{f['path']}:{f['sha256']}" for f in sorted(self.files, key=lambda f: f["path"])).encode()
        ).hexdigest()
        manifest = {
            "market": self.market,
            "source": self.source,
            "dataset_id": self.dataset_id,
            "version": self.version,
            "period_start": _iso(self.period_start),
            "period_end": _iso(self.period_end),
            "published_at": _iso(self.published_at),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "raw_uri": str(self.dir),
            "checksum_sha256": combined,
            "row_count": self.row_count,
            "total_bytes": sum(f["bytes"] for f in self.files),
            "files": self.files,
            "meta": self.meta,
        }
        manifest["release_id"] = db.register_release(manifest)
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
        return manifest


def _iso(v):
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)
