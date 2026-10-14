"""London Planning Datahub → mkt_uk.planning_application (đơn xin cấp phép quy hoạch gần đây, có toạ độ)."""
from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime

from .base import LoadContext, LoadError, Loader

log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.planning_application (
    id text PRIMARY KEY,
    lpa text, reference text, address text, postcode text, description text,
    app_type text, app_type_full text, development_type text, status text, decision text,
    valid_date date, decision_date date, url text, ward text,
    geom geometry(Point, 4326),
    source text NOT NULL,
    release_id bigint REFERENCES ops.dataset_release (id)
);
CREATE INDEX IF NOT EXISTS planning_application_geom ON mkt_uk.planning_application USING gist (geom);
CREATE INDEX IF NOT EXISTS planning_application_valid ON mkt_uk.planning_application (valid_date);
COMMENT ON TABLE mkt_uk.planning_application IS 'Đơn xin cấp phép quy hoạch gần đây có toạ độ. London: London Planning Datahub (GLA, OGL).'"""
COLS = ["id", "lpa", "reference", "address", "postcode", "description", "app_type", "app_type_full", "development_type",
        "status", "decision", "valid_date", "decision_date", "url", "ward", "x", "y"]


def dmy(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        return None


class LondonPlanningLoader(Loader):
    source = "london_planning"
    description = "London Planning Datahub → mkt_uk.planning_application (source = 'london_datahub')"

    def load(self, ctx: LoadContext) -> dict:
        rows, bad = [], 0
        with gzip.open(ctx.file(r"london_planning\.jsonl\.gz$"), "rt") as fh:
            for line in fh:
                d = json.loads(line)
                x, y = d.get("centroid_easting"), d.get("centroid_northing")
                try:
                    x, y = float(x), float(y)
                except (TypeError, ValueError):
                    x = y = None
                if x is not None and not (500_000 <= x <= 565_000 and 150_000 <= y <= 205_000):
                    x = y = None  # ngoài London: toạ độ lỗi
                    bad += 1
                addr = " ".join(str(v) for v in (d.get("site_name"), d.get("site_number"), d.get("street_name")) if v)
                rows.append((d["id"], d.get("lpa_name"), d.get("lpa_app_no"), addr or None, (d.get("postcode") or "").strip() or None,
                             (d.get("description") or "")[:2000] or None, d.get("application_type"), d.get("application_type_full"),
                             d.get("development_type"), d.get("status"), d.get("decision"), dmy(d.get("valid_date")),
                             dmy(d.get("decision_date")), d.get("url_planning_app"), d.get("ward"), x, y))
        with_geom = sum(1 for r in rows if r[-1] is not None)
        lpas = {r[1] for r in rows}
        log.info("    %s hồ sơ, %s có toạ độ, %s cơ quan quy hoạch, %s toạ độ ngoài London", f"{len(rows):,}", f"{with_geom:,}", len(lpas), bad)
        if len(rows) < 100_000 or with_geom < 0.8 * len(rows) or not 33 <= len(lpas) <= 40:
            raise LoadError(f"Dữ liệu planning London bất thường: {len(rows)} hồ sơ, {with_geom} có toạ độ, {len(lpas)} LPA")
        ctx.conn.execute(DDL)
        st = ctx.stage_table("pa", COLS, {"valid_date": "date", "decision_date": "date", "x": "float8", "y": "float8"})
        ctx.copy_rows(st, COLS, rows, "COPY planning London")
        ctx.sql("thay dữ liệu London", "DELETE FROM mkt_uk.planning_application WHERE source = 'london_datahub'")
        n = ctx.sql("ghi planning London", f"""
            INSERT INTO mkt_uk.planning_application (id, lpa, reference, address, postcode, description, app_type, app_type_full,
                development_type, status, decision, valid_date, decision_date, url, ward, geom, source, release_id)
            SELECT DISTINCT ON (id) id, lpa, reference, address, postcode, description, app_type, app_type_full, development_type,
                   status, decision, valid_date, decision_date, url, ward,
                   CASE WHEN x IS NOT NULL THEN ST_Transform(ST_SetSRID(ST_MakePoint(x, y), 27700), 4326) END, 'london_datahub', %s
            FROM {st} ORDER BY id""", (ctx.release_id,))
        ctx.conn.execute("ANALYZE mkt_uk.planning_application")
        ctx.drop_stage("pa")
        return {"applications": n, "with_geom": with_geom, "lpas": len(lpas)}
