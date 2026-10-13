"""Chạy loader: `python -m uk load <source...|all> [--cleanup] [--force]`.

Quy trình cho mỗi nguồn:
  1. Chọn release mới nhất đã tải đủ (có manifest.json, file thô còn).
  2. Kiểm tra các nguồn phụ thuộc đã 'loaded'.
  3. Chạy loader trong MỘT transaction; mọi kiểm tra số dòng phải qua, lỗi → rollback toàn bộ.
  4. Thành công → ops.dataset_release.status='loaded' (+ row_count, thống kê) → commit.
  5. Chỉ khi có --cleanup và bước 4 đã commit: xoá file thô, giữ manifest.json.
"""
from __future__ import annotations

import json
import logging
import time
import traceback
from pathlib import Path

import psycopg

from common import db
from common.config import data_root, database_url

from .loaders import LOADER_BY_SOURCE, LOADERS
from .loaders.base import STAGE, LoadContext

log = logging.getLogger("uk.load")


def latest_release_dir(source: str) -> Path | None:
    d = data_root("uk") / source
    if not d.is_dir():
        return None
    cands = [p for p in d.iterdir() if (p / "manifest.json").is_file()]
    if not cands:
        return None
    return max(cands, key=lambda p: json.loads((p / "manifest.json").read_text()).get("fetched_at", ""))


def release_row(conn, dataset_id: str, version: str):
    return conn.execute("SELECT id, status FROM ops.dataset_release WHERE dataset_id=%s AND version_label=%s",
                        (dataset_id, version)).fetchone()


def delete_raw(rel_dir: Path, reason: str) -> int:
    mpath = rel_dir / "manifest.json"
    files = [p for p in rel_dir.iterdir() if p.is_file() and p.name != "manifest.json"]
    size = sum(p.stat().st_size for p in files)
    for p in files:
        p.unlink()
    m = json.loads(mpath.read_text())
    m["raw_deleted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    m["raw_deleted_reason"] = reason
    mpath.write_text(json.dumps(m, ensure_ascii=False, indent=2))
    log.info("    đã xoá %s file thô (%.1f MB) trong %s", len(files), size / 1e6, rel_dir)
    return size


def analyze_changed(conn, source: str) -> list[str]:
    """ANALYZE bảng core/mkt_uk đổi nhiều kể từ lần thống kê trước. Thống kê cũ làm planner
    chọn sai index (vd. core.poi tưởng 1 nhà trẻ → quét cả 28k dòng, trang web timeout)."""
    done: list[str] = []
    try:
        rows = conn.execute("""SELECT schemaname || '.' || relname FROM pg_stat_user_tables
                               WHERE schemaname IN ('core', 'mkt_uk')
                                 AND n_mod_since_analyze > greatest(10000, 0.05 * n_live_tup)""").fetchall()
        for (t,) in rows:
            t0 = time.monotonic()
            conn.execute(f"ANALYZE {t}")
            conn.commit()
            done.append(t)
            log.info("[%s] ANALYZE %s (%.1fs)", source, t, time.monotonic() - t0)
    except Exception:
        conn.rollback()
        log.error("[%s] ANALYZE sau khi nạp thất bại (dữ liệu đã commit, không ảnh hưởng):\n%s", source, traceback.format_exc())
    return done


def run_load(names: list[str], cleanup: bool, force: bool) -> int:
    from .sources import BY_NAME
    if names == ["all"]:
        todo = LOADERS
    else:
        unknown = [n for n in names if n not in LOADER_BY_SOURCE]
        if unknown:
            log.error("Không có loader cho: %s. Có: %s", unknown, ", ".join(LOADER_BY_SOURCE))
            return 2
        todo = [l for l in LOADERS if l.source in names]  # giữ thứ tự phụ thuộc

    url = database_url()
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(f"CREATE SCHEMA IF NOT EXISTS {STAGE}")
    results = []
    for loader in todo:
        src = BY_NAME[loader.source]
        res = {"source": loader.source}
        results.append(res)
        rel_dir = latest_release_dir(loader.source)
        if rel_dir is None:
            res["status"] = "no-data"
            log.warning("[%s] chưa có bản tải nào — chạy `python -m uk %s` trước", loader.source, loader.source)
            continue
        manifest = json.loads((rel_dir / "manifest.json").read_text())
        res["version"] = manifest["version"]
        if manifest.get("raw_deleted_at"):
            res["status"] = "raw-deleted"
            log.info("[%s] %s: file thô đã xoá (đã nạp trước đó), bỏ qua", loader.source, manifest["version"])
            continue

        conn = psycopg.connect(url, autocommit=False)
        try:
            row = release_row(conn, src.dataset_id, manifest["version"])
            if row is None:
                raise RuntimeError(f"Không thấy ops.dataset_release cho {src.dataset_id}/{manifest['version']} "
                                   "— tải lại với --force để đăng ký release")
            manifest["release_id"], status = row
            conn.commit()
            if status == "loaded" and not force:
                res["status"] = "already-loaded"
                log.info("[%s] %s đã nạp (release %s)%s", loader.source, manifest["version"], row[0],
                         ", xoá file thô" if cleanup else ", bỏ qua")
                if cleanup:
                    delete_raw(rel_dir, f"release {row[0]} status=loaded")
                continue
            missing = []
            for dep in loader.depends_on:
                dsrc = BY_NAME[dep]
                ok = conn.execute("SELECT 1 FROM ops.dataset_release WHERE dataset_id=%s AND status IN ('loaded','published')",
                                  (dsrc.dataset_id,)).fetchone()
                if not ok:
                    missing.append(dep)
            conn.commit()
            if missing:
                res["status"] = "blocked"
                log.error("[%s] chưa nạp được: cần nạp trước %s", loader.source, missing)
                continue

            log.info("[%s] NẠP %s (release %s) từ %s", loader.source, manifest["version"], manifest["release_id"], rel_dir)
            run_id = db.start_run(f"load:{loader.source}", src.dataset_id)
            t0 = time.monotonic()
            conn.execute("SET work_mem = '256MB'")
            ctx = LoadContext(conn, manifest, rel_dir)
            try:
                stats = loader.load(ctx) or {}
                stats.update(ctx.stats)
                rows = sum(v for k, v in ctx.stats.items() if isinstance(v, int) and not k.startswith("unmatched"))
                conn.execute("""UPDATE ops.dataset_release SET status='loaded', row_count=%s,
                                validation_report = coalesce(validation_report, '{}'::jsonb) || jsonb_build_object('load', %s::jsonb)
                                WHERE id=%s""", (rows, json.dumps(stats, default=str), manifest["release_id"]))
                conn.commit()
            except BaseException as e:
                conn.rollback()
                tb = traceback.format_exc()
                log.error("[%s] NẠP THẤT BẠI, đã rollback toàn bộ. File thô giữ nguyên.\n%s", loader.source, tb)
                (rel_dir / "last_load_error.txt").write_text(
                    f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}\nsource: {loader.source}\nversion: {manifest['version']}\n"
                    f"etl_run_id: {run_id}\n\n{tb}")
                db.finish_run(run_id, "cancelled" if isinstance(e, KeyboardInterrupt) else "failed",
                              {"seconds": round(time.monotonic() - t0, 1)}, release_id=manifest["release_id"], error=tb[-8000:])
                res.update(status="failed", error=f"{type(e).__name__}: {str(e)[:500]}")
                if isinstance(e, KeyboardInterrupt):
                    raise
                continue
            analyzed = analyze_changed(conn, loader.source)
            if analyzed:
                stats["analyzed"] = analyzed
            secs = round(time.monotonic() - t0, 1)
            stats["seconds"] = secs
            db.finish_run(run_id, "succeeded", stats, release_id=manifest["release_id"])
            (rel_dir / "last_load_error.txt").unlink(missing_ok=True)
            res.update(status="loaded", seconds=secs, stats=stats)
            log.info("[%s] ✓ đã nạp và commit trong %ss: %s", loader.source, secs, json.dumps(stats, default=str, ensure_ascii=False)[:600])
            if cleanup:
                delete_raw(rel_dir, f"release {manifest['release_id']} nạp xong {time.strftime('%Y-%m-%d %H:%M')}")
        except Exception as e:
            conn.rollback()
            log.error("[%s] lỗi ngoài loader:\n%s", loader.source, traceback.format_exc())
            res.update(status="failed", error=f"{type(e).__name__}: {e}")
        finally:
            conn.close()
    metric_sources = {"iod2025", "census2021", "uk_hpi", "pipr", "ons_income_msoa", "defra_pcm"}
    if any(r["status"] == "loaded" and r["source"] in metric_sources for r in results):
        t0 = time.monotonic()
        try:
            with psycopg.connect(url, autocommit=True) as c:
                c.execute("REFRESH MATERIALIZED VIEW core.metric_latest")
                n = c.execute("SELECT count(*) FROM core.metric_latest").fetchone()[0]
            log.info("REFRESH core.metric_latest: %s dòng, %.1fs", f"{n:,}", time.monotonic() - t0)
        except Exception:
            log.error("REFRESH core.metric_latest lỗi:\n%s", traceback.format_exc())
    print(json.dumps(results, indent=1, ensure_ascii=False, default=str))
    failed = [r["source"] for r in results if r["status"] in ("failed", "blocked")]
    if failed:
        log.error("Tổng kết nạp: lỗi/chặn ở %s", ", ".join(failed))
    return 1 if failed else 0
