"""`python -m uk derive <bước...|all>`: chạy bước tính toán, mỗi bước một transaction, ghi ops.etl_run."""
from __future__ import annotations

import json
import logging
import time
import traceback

import psycopg

from common import db
from common.config import database_url

from .derive import STEP_BY_NAME, STEPS
from .derive.base import DERIVED_DATASET
from .loaders.base import STAGE, LoadContext
from .sources import BY_NAME

log = logging.getLogger("uk.derive")


def run_derive(names: list[str]) -> int:
    todo = STEPS if names == ["all"] else [s for s in STEPS if s.name in names]
    unknown = [n for n in names if n != "all" and n not in STEP_BY_NAME]
    if unknown:
        log.error("Không có bước: %s. Có: %s", unknown, ", ".join(STEP_BY_NAME))
        return 2
    url = database_url()
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(f"CREATE SCHEMA IF NOT EXISTS {STAGE}")
        loaded = {r[0] for r in c.execute("SELECT DISTINCT dataset_id FROM ops.dataset_release WHERE status IN ('loaded','published')")}
        done = {r[0].split(":", 1)[1] for r in c.execute(
            "SELECT DISTINCT job_name FROM ops.etl_run WHERE job_name LIKE 'derive:%' AND status='succeeded'")}
    results = []
    for step in todo:
        res = {"step": step.name}
        results.append(res)
        missing = [s for s in step.needs_sources if BY_NAME[s].dataset_id not in loaded]
        missing += [d for d in step.depends_on if d not in done and d not in {r["step"] for r in results if r.get("status") == "ok"}]
        if missing:
            res["status"] = "blocked"
            log.error("[%s] chưa chạy được: thiếu %s", step.name, missing)
            continue
        log.info("[%s] BẮT ĐẦU: %s", step.name, step.description)
        run_id = db.start_run(f"derive:{step.name}", DERIVED_DATASET)
        t0 = time.monotonic()
        conn = psycopg.connect(url, autocommit=False)
        try:
            conn.execute("SET work_mem = '256MB'")
            ctx = LoadContext(conn, {"release_id": None, "version": time.strftime("%Y-%m-%d")}, None)
            stats = step.run(ctx) or {}
            stats.update(ctx.stats)
            conn.commit()
        except BaseException as e:
            conn.rollback()
            tb = traceback.format_exc()
            log.error("[%s] THẤT BẠI, đã rollback.\n%s", step.name, tb)
            db.finish_run(run_id, "failed", {"seconds": round(time.monotonic() - t0, 1)}, error=tb[-8000:])
            res.update(status="failed", error=f"{type(e).__name__}: {str(e)[:500]}")
            if isinstance(e, KeyboardInterrupt):
                raise
            continue
        finally:
            conn.close()
        stats["seconds"] = round(time.monotonic() - t0, 1)
        db.finish_run(run_id, "succeeded", stats)
        res.update(status="ok", **stats)
        log.info("[%s] ✓ xong trong %ss: %s", step.name, stats["seconds"], json.dumps(stats, ensure_ascii=False, default=str)[:600])
    print(json.dumps(results, indent=1, ensure_ascii=False, default=str))
    return 1 if any(r["status"] != "ok" for r in results) else 0
