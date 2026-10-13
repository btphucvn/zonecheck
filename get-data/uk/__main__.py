"""CLI cào dữ liệu UK.

    python -m uk list                       # liệt kê tool + bản đã tải
    python -m uk <source> [tuỳ chọn]        # tải một nguồn, ví dụ: python -m uk police --month 2026-08
    python -m uk <source> --dry-run         # chỉ xem phiên bản mới nhất, không tải
    python -m uk all [--skip ppd,police]    # tải lần lượt mọi nguồn (lỗi một nguồn không dừng cả lượt)
    python -m uk load <source...|all> [--cleanup]   # nạp vào DB; --cleanup xoá file thô SAU KHI nạp thành công
    python -m uk cleanup [--yes]            # xoá file thô của bản đã nạp vào DB (loaded/published), giữ manifest.json

Dữ liệu lưu ở get-data/uk/data/<source>/<version>/ (đổi gốc bằng ZC_DATA_DIR).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback

from common import db
from common.config import data_root
from common.logs import log_dir, setup_logging

from .sources import BY_NAME, SOURCES

log = logging.getLogger("uk")


def run_source(src, args) -> dict:
    t0 = time.monotonic()
    if src.name in RETIRED and not args.force:
        log.info("[%s] ngưng dùng, bỏ qua (%s). --force để vẫn tải", src.name, RETIRED[src.name])
        return {"source": src.name, "status": "retired"}
    try:
        rel = src.plan(args)
    except Exception:
        log.error("[%s] lỗi khi xác định phiên bản mới nhất (plan):\n%s", src.name, traceback.format_exc())
        raise
    log.info("[%s] phiên bản mới nhất: %s → %s", src.name, rel.version, rel.dir)
    if args.dry_run:
        return {"source": src.name, "version": rel.version, "status": "dry-run"}
    if rel.is_complete() and not args.force:
        log.info("[%s] đã có đủ, bỏ qua (dùng --force để tải lại)", src.name)
        return {"source": src.name, "version": rel.version, "status": "skipped"}
    if args.force:
        rel.reset()
    run_id = db.start_run(f"fetch:{src.name}", src.dataset_id)
    log.debug("[%s] etl_run id=%s, args=%s", src.name, run_id, vars(args))
    try:
        src.download(rel, args)
        manifest = rel.finish()
    except BaseException as e:
        tb = traceback.format_exc()
        status = "cancelled" if isinstance(e, KeyboardInterrupt) else "failed"
        log.error("[%s] %s ở phiên bản %s (etl_run id=%s, thư mục %s)\n%s",
                  src.name, status.upper(), rel.version, run_id, rel.dir, tb)
        # giữ file đã tải dở để lần sau resume; ghi lại lỗi ngay cạnh dữ liệu
        try:
            rel.path("last_error.txt").write_text(
                f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}\nsource: {src.name}\nversion: {rel.version}\n"
                f"etl_run_id: {run_id}\nargs: {vars(args)}\nfiles_done: {[f['path'] for f in rel.files]}\n\n{tb}")
        except OSError:
            log.exception("Không ghi được last_error.txt")
        db.finish_run(run_id, status, {"files_done": len(rel.files)}, error=tb[-8000:])
        raise
    (rel.dir / "last_error.txt").unlink(missing_ok=True)
    stats = {"version": rel.version, "files": len(manifest["files"]), "bytes": manifest["total_bytes"],
             "rows": manifest["row_count"], "seconds": round(time.monotonic() - t0, 1)}
    db.finish_run(run_id, "succeeded", stats, release_id=manifest["release_id"])
    log.info("[%s] xong: %s file, %.1f MB, %ss", src.name, stats["files"], stats["bytes"] / 1e6, stats["seconds"])
    return {"source": src.name, "status": "fetched", **stats}


def cmd_list() -> None:
    root = data_root("uk")
    for s in SOURCES:
        d = root / s.name
        versions = sorted(p.name for p in d.iterdir() if (p / "manifest.json").is_file()) if d.is_dir() else []
        print(f"{s.name:20} {s.dataset_id:28} {versions[-1] if versions else '-':22} {s.description}")


# Nguồn cố ý không nạp DB (đã có nguồn thay thế): cleanup đặt release thành 'superseded' rồi xoá file thô
RETIRED = {
    "os_codepoint_open": "Trùng ONSPD (toạ độ postcode đã có trong mkt_uk.postcode)",
    "journey_time": "JTS 2019 theo LSOA 2011, đã thay bằng DfT Transport connectivity 2025 (uk.tcm.*)",
}


def cmd_cleanup(yes: bool) -> int:
    """Xoá file thô của các release mà ops.dataset_release đã ở trạng thái loaded/published.

    Giữ manifest.json (sha256, url nguồn) để truy vết và để lần sau không tải lại cùng phiên bản.
    Mặc định chỉ liệt kê; cần --yes mới xoá.
    """
    loaded = db.loaded_releases([s.dataset_id for s in SOURCES])
    if loaded is None:
        log.error("cleanup cần kết nối DB để biết bản nào đã nạp — không xoá gì")
        return 1
    root = data_root("uk")
    total = 0
    for s in SOURCES:
        sdir = root / s.name
        if not sdir.is_dir():
            continue
        for vdir in sorted(p for p in sdir.iterdir() if p.is_dir()):
            mpath = vdir / "manifest.json"
            if not mpath.is_file():
                continue
            status = loaded.get((s.dataset_id, vdir.name))
            files = [p for p in vdir.iterdir() if p.is_file() and p.name != "manifest.json"]
            if not status and s.name in RETIRED and files:
                status = "superseded"
                log.info("[%s] không nạp: %s", s.name, RETIRED[s.name])
                if yes:
                    db.conn().execute("""UPDATE ops.dataset_release SET status = 'superseded',
                        validation_report = coalesce(validation_report, '{}'::jsonb) || jsonb_build_object('retired', %s::text)
                        WHERE dataset_id = %s AND version_label = %s""", (RETIRED[s.name], s.dataset_id, vdir.name))
            if not status or not files:
                continue
            size = sum(p.stat().st_size for p in files)
            total += size
            log.info("[%s] %s (%s): %s file, %.1f MB%s", s.name, vdir.name, status, len(files), size / 1e6,
                     "" if yes else " — sẽ xoá (thêm --yes)")
            if yes:
                for p in files:
                    p.unlink()
                manifest = json.loads(mpath.read_text())
                manifest["raw_deleted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                manifest["raw_deleted_reason"] = f"release status={status} trong DB" + (
                    f": {RETIRED[s.name]}" if status == "superseded" else "")
                mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
                log.debug("đã xoá %s", [p.name for p in files])
    log.info("Tổng %s: %.1f MB", "đã xoá" if yes else "có thể xoá", total / 1e6)
    return 0


def main(argv=None) -> int:
    logfile = setup_logging("uk")
    log.debug("=== bắt đầu: python -m uk %s", " ".join(argv if argv is not None else sys.argv[1:]))
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--force", action="store_true", help="tải lại dù đã có bản này")
    common.add_argument("--dry-run", action="store_true", help="chỉ xác định phiên bản, không tải")

    parser = argparse.ArgumentParser(prog="python -m uk", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="liệt kê nguồn")
    p_load = sub.add_parser("load", help="nạp bản mới nhất đã tải vào DB")
    p_load.add_argument("sources", nargs="+", help="tên nguồn hoặc 'all'")
    p_load.add_argument("--cleanup", action="store_true", help="xoá file thô sau khi nạp + commit thành công")
    p_load.add_argument("--force", action="store_true", help="nạp lại dù release đã loaded")
    p_der = sub.add_parser("derive", help="tính tổng hợp / phân vị / điểm từ dữ liệu đã nạp")
    p_der.add_argument("steps", nargs="+", help="tên bước hoặc 'all'")
    p_clean = sub.add_parser("cleanup", help="xoá file thô của bản đã nạp vào DB, giữ manifest.json")
    p_clean.add_argument("--yes", action="store_true", help="xoá thật (mặc định chỉ liệt kê)")
    p_all = sub.add_parser("all", parents=[common], help="tải mọi nguồn với tuỳ chọn mặc định")
    p_all.add_argument("--skip", default="", help="bỏ qua các nguồn, phân tách bằng dấu phẩy")
    p_all.add_argument("--only", default="", help="chỉ chạy các nguồn này, phân tách bằng dấu phẩy")
    for s in SOURCES:
        p = sub.add_parser(s.name, parents=[common], help=s.description)
        s.add_arguments(p)

    args = parser.parse_args(argv)
    if args.cmd == "list":
        cmd_list()
        return 0
    if args.cmd == "load":
        from .loadrun import run_load
        return run_load(args.sources, args.cleanup, args.force)
    if args.cmd == "derive":
        from .deriverun import run_derive
        return run_derive(args.steps)
    if args.cmd == "cleanup":
        return cmd_cleanup(args.yes)
    if args.cmd != "all":
        try:
            run_source(BY_NAME[args.cmd], args)
        except Exception as e:
            log.error("[%s] thất bại: %s: %s — chi tiết: %s, %s", args.cmd, type(e).__name__, e,
                      logfile, log_dir() / "uk-errors.log")
            return 1
        return 0

    skip = set(filter(None, args.skip.split(",")))
    only = set(filter(None, args.only.split(",")))
    results = []
    for s in SOURCES:
        if s.name in skip or (only and s.name not in only):
            continue
        # tuỳ chọn riêng của từng nguồn lấy giá trị mặc định
        p = argparse.ArgumentParser(add_help=False)
        s.add_arguments(p)
        sargs = p.parse_args([])
        sargs.force, sargs.dry_run = args.force, args.dry_run
        try:
            results.append(run_source(s, sargs))
        except KeyboardInterrupt:
            raise
        except Exception as e:
            # traceback đã được run_source ghi vào log
            log.error("[%s] LỖI: %s: %s", s.name, type(e).__name__, e)
            results.append({"source": s.name, "status": "failed", "error": f"{type(e).__name__}: {e}"})
    print(json.dumps(results, indent=1, ensure_ascii=False, default=str))
    failed = [r["source"] for r in results if r["status"] == "failed"]
    if failed:
        log.error("Tổng kết: %s/%s nguồn lỗi: %s — xem %s", len(failed), len(results), ", ".join(failed), logfile)
    return 1 if any(r["status"] == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
