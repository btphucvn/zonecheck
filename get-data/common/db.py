"""Ghi vết vào schema ops: ops.etl_run (mỗi lần chạy) và ops.dataset_release (mỗi bản tải về).

Không bắt buộc: nếu không có DATABASE_URL hoặc không kết nối được thì chỉ cảnh báo, việc tải vẫn chạy.
"""
from __future__ import annotations

import json
import logging
import socket
import subprocess

from .config import REPO_DIR, database_url

log = logging.getLogger(__name__)

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

_conn = None
_disabled = False


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_DIR), "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return None


def conn():
    global _conn, _disabled
    if _disabled:
        return None
    if _conn is not None and not _conn.closed:
        return _conn
    url = database_url()
    if not url or psycopg is None:
        log.warning("Bỏ qua ghi DB (%s)", "chưa cài psycopg" if psycopg is None else "không có DATABASE_URL")
        _disabled = True
        return None
    try:
        _conn = psycopg.connect(url, autocommit=True, connect_timeout=10)
    except Exception as e:
        safe = url.split("@")[-1]  # không log mật khẩu
        log.warning("Không kết nối được DB (%s), bỏ qua ghi DB: %s", safe, e, exc_info=True)
        _disabled = True
        return None
    return _conn


def start_run(job_name: str, dataset_id: str, trigger_kind: str = "manual") -> int | None:
    c = conn()
    if c is None:
        return None
    try:
        row = c.execute(
            """INSERT INTO ops.etl_run (job_name, dataset_id, trigger_kind, git_sha, host)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (job_name, dataset_id, trigger_kind, _git_sha(), socket.gethostname()),
        ).fetchone()
        return row[0]
    except Exception as e:
        log.warning("Không ghi được ops.etl_run (dataset %s đã chạy uk/seed.sql chưa?): %s", dataset_id, e, exc_info=True)
        return None


def finish_run(run_id: int | None, status: str, stats: dict | None = None,
               release_id: int | None = None, error: str | None = None) -> None:
    c = conn()
    if c is None or run_id is None:
        return
    try:
        _finish_run(c, run_id, status, stats, release_id, error)
    except Exception as e:
        log.warning("Không cập nhật được ops.etl_run id=%s: %s", run_id, e, exc_info=True)


def _finish_run(c, run_id, status, stats, release_id, error):
    c.execute(
        """UPDATE ops.etl_run SET status = %s, finished_at = now(), stats = %s::jsonb,
                  release_id = coalesce(%s, release_id), error_message = %s
           WHERE id = %s""",
        (status, json.dumps(stats or {}, default=str), release_id, error, run_id),
    )


def register_release(manifest: dict) -> int | None:
    """Upsert ops.dataset_release theo (dataset_id, version_label). Trả về release id."""
    c = conn()
    if c is None:
        return None
    try:
        row = c.execute(
            """INSERT INTO ops.dataset_release
                 (dataset_id, version_label, period_start, period_end, published_at,
                  raw_uri, checksum_sha256, row_count, status, validation_report)
               VALUES (%(dataset_id)s, %(version)s, %(period_start)s, %(period_end)s, %(published_at)s,
                       %(raw_uri)s, %(checksum)s, %(row_count)s, 'fetched', %(report)s::jsonb)
               ON CONFLICT (dataset_id, version_label) DO UPDATE SET
                 raw_uri = EXCLUDED.raw_uri, checksum_sha256 = EXCLUDED.checksum_sha256,
                 fetched_at = now(), validation_report = EXCLUDED.validation_report,
                 period_start = coalesce(EXCLUDED.period_start, ops.dataset_release.period_start),
                 period_end = coalesce(EXCLUDED.period_end, ops.dataset_release.period_end),
                 published_at = coalesce(EXCLUDED.published_at, ops.dataset_release.published_at)
               RETURNING id""",
            {
                "dataset_id": manifest["dataset_id"],
                "version": manifest["version"],
                "period_start": manifest.get("period_start"),
                "period_end": manifest.get("period_end"),
                "published_at": manifest.get("published_at"),
                "raw_uri": manifest["raw_uri"],
                "checksum": manifest["checksum_sha256"],
                "row_count": manifest.get("row_count"),
                "report": json.dumps({"files": manifest["files"], "meta": manifest.get("meta", {})}, default=str),
            },
        ).fetchone()
        return row[0]
    except Exception as e:
        log.warning("Không ghi được ops.dataset_release cho %s/%s: %s", manifest.get("dataset_id"),
                    manifest.get("version"), e, exc_info=True)
        return None


def loaded_releases(dataset_ids: list[str]) -> dict[tuple[str, str], str] | None:
    """{(dataset_id, version_label): status} cho các release đã nạp vào DB (loaded/published). None nếu không có DB."""
    c = conn()
    if c is None:
        return None
    rows = c.execute(
        """SELECT dataset_id, version_label, status FROM ops.dataset_release
           WHERE dataset_id = ANY(%s) AND status IN ('loaded', 'published')""",
        (dataset_ids,),
    ).fetchall()
    return {(d, v): st for d, v, st in rows}
