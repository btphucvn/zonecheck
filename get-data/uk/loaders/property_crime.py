"""Nạp Price Paid → mkt_uk.price_paid; police archive → mkt_uk.crime_incident + crime_coverage_gap."""
from __future__ import annotations

import json
import logging
import zipfile

from .base import LoadContext, LoadError, Loader

log = logging.getLogger(__name__)

PPD_COLS = ["tx", "price", "dt", "postcode", "ptype", "old_new", "duration", "paon", "saon", "street",
            "locality", "town", "district", "county", "category", "record_status"]

PPD_INDEXES = {
    "price_paid_postcode_date": "CREATE INDEX price_paid_postcode_date ON mkt_uk.price_paid (postcode, transfer_date DESC)",
    "price_paid_lsoa_date": "CREATE INDEX price_paid_lsoa_date ON mkt_uk.price_paid (lsoa21_code, transfer_date)",
    "price_paid_date": "CREATE INDEX price_paid_date ON mkt_uk.price_paid (transfer_date)",
    "price_paid_uprn": "CREATE INDEX price_paid_uprn ON mkt_uk.price_paid (uprn) WHERE uprn IS NOT NULL",
}

PPD_SELECT = """
    SELECT trim(both '{{}}' from s.tx)::uuid, s.price::int, s.dt::date, nullif(s.postcode, ''), s.ptype,
           s.old_new = 'Y', s.duration, nullif(s.paon, ''), nullif(s.saon, ''), nullif(s.street, ''),
           nullif(s.locality, ''), nullif(s.town, ''), s.category, p.area_id, p.lsoa21_code, p.geom, %(rel)s
    FROM {stage} s LEFT JOIN mkt_uk.postcode p ON p.postcode = nullif(s.postcode, '')"""
PPD_TARGET = """mkt_uk.price_paid (transaction_id, price, transfer_date, postcode, property_type, is_new_build, tenure,
    paon, saon, street, locality, town, ppd_category, area_id, lsoa21_code, geom, release_id)"""


class PricePaidLoader(Loader):
    source = "ppd"
    depends_on = ("onspd",)
    description = "Price Paid → mkt_uk.price_paid (complete: thay toàn bộ; monthly: thêm/sửa/xoá theo record status)"

    def load(self, ctx: LoadContext) -> dict:
        mode = ctx.manifest.get("meta", {}).get("mode", "complete")
        f = ctx.file(r"^pp-.*\.csv$")
        t = ctx.stage_table("ppd", PPD_COLS)
        with open(f, "rb") as fh:
            n = ctx.copy_csv(t, fh, header=False, label=f"COPY {f.name}")
        bad = ctx.scalar(f"SELECT count(*) FROM {t} WHERE tx !~ '^\\{{[0-9A-F-]{{36}}\\}}$' OR price !~ '^[0-9]+$'")
        if bad:
            sample = ctx.conn.execute(f"SELECT * FROM {t} WHERE tx !~ '^\\{{[0-9A-F-]{{36}}\\}}$' OR price !~ '^[0-9]+$' LIMIT 3").fetchall()
            raise LoadError(f"{bad} dòng PPD sai định dạng, ví dụ: {sample}")
        params = {"rel": ctx.release_id}

        if mode in ("complete",):
            # thay toàn bộ: bỏ index → TRUNCATE → INSERT → tạo lại index (nhanh hơn nhiều so với upsert 30 triệu dòng)
            for name in PPD_INDEXES:
                ctx.conn.execute(f"DROP INDEX IF EXISTS mkt_uk.{name}")
            ctx.sql("TRUNCATE price_paid (+ ppd_epc_match)", "TRUNCATE mkt_uk.price_paid CASCADE")
            with ctx.without_fks("mkt_uk.price_paid"):
                # 31 triệu dòng × 2,7 triệu postcode: ép hash join (nested loop + tra index ngẫu nhiên rất chậm)
                ctx.conn.execute("SET LOCAL enable_nestloop = off")
                ctx.sql("INSERT price_paid", f"INSERT INTO {PPD_TARGET} {PPD_SELECT.format(stage=t)}", params)
                ctx.conn.execute("SET LOCAL enable_nestloop = on")
                for name, ddl in PPD_INDEXES.items():
                    ctx.sql(f"index {name}", ddl)
            n_db = ctx.scalar("SELECT count(*) FROM mkt_uk.price_paid")
            ctx.expect("mkt_uk.price_paid", n_db, n)
        else:
            # file tháng/năm: A = thêm, C = sửa, D = xoá
            ctx.sql("xoá bản ghi D", f"""DELETE FROM mkt_uk.price_paid pp USING {t} s
                WHERE s.record_status = 'D' AND pp.transaction_id = trim(both '{{}}' from s.tx)::uuid""")
            ctx.sql("upsert bản ghi A/C", f"""
                INSERT INTO {PPD_TARGET} {PPD_SELECT.format(stage=t)} WHERE s.record_status IN ('A', 'C')
                ON CONFLICT (transaction_id) DO UPDATE SET price = EXCLUDED.price, transfer_date = EXCLUDED.transfer_date,
                    postcode = EXCLUDED.postcode, property_type = EXCLUDED.property_type,
                    is_new_build = EXCLUDED.is_new_build, tenure = EXCLUDED.tenure, paon = EXCLUDED.paon,
                    saon = EXCLUDED.saon, street = EXCLUDED.street, locality = EXCLUDED.locality, town = EXCLUDED.town,
                    ppd_category = EXCLUDED.ppd_category, area_id = EXCLUDED.area_id,
                    lsoa21_code = EXCLUDED.lsoa21_code, geom = EXCLUDED.geom, release_id = EXCLUDED.release_id""", params)
        no_pc = ctx.scalar("SELECT count(*) FROM mkt_uk.price_paid WHERE release_id = %s AND area_id IS NULL",
                           (ctx.release_id,))
        log.info("    giao dịch không ghép được postcode (postcode trống/không có trong ONSPD): %s", f"{no_pc:,}")
        ctx.stats["unmatched_postcode"] = no_pc
        ctx.conn.execute("ANALYZE mkt_uk.price_paid")
        ctx.drop_stage("ppd")
        return {"rows_in_file": n, "mode": mode}


CRIME_COLS = ["crime_id", "month", "reported_by", "falls_within", "longitude", "latitude", "location",
              "lsoa_code", "lsoa_name", "crime_type", "last_outcome", "context"]


class PoliceLoader(Loader):
    source = "police"
    description = "data.police.uk archive (36 tháng street crime) → mkt_uk.crime_incident; tháng thiếu → crime_coverage_gap"

    def load(self, ctx: LoadContext) -> dict:
        z = ctx.file(r"^police-archive-.*\.zip$")
        t = ctx.stage_table("crime", CRIME_COLS)
        total, months = 0, set()
        with zipfile.ZipFile(z) as zf:
            members = sorted(n for n in zf.namelist() if n.endswith("-street.csv"))
            if not members:
                raise LoadError(f"Không có file *-street.csv trong {z.name}")
            for i, m in enumerate(members, 1):
                months.add(m.split("/")[0])
                with zf.open(m) as f:
                    with ctx.conn.cursor() as cur:
                        with cur.copy(f"COPY {t} FROM STDIN WITH (FORMAT csv, HEADER true)") as cp:
                            while chunk := f.read(1 << 20):
                                cp.write(chunk)
                        total += cur.rowcount
                if i % 200 == 0 or i == len(members):
                    log.info("    COPY street csv: %s/%s file, %s dòng", i, len(members), f"{total:,}")
        months = sorted(months)
        log.info("    tháng trong archive: %s → %s (%s tháng)", months[0], months[-1], len(months))

        # partition theo năm phải có trước khi insert (partition _default phải luôn rỗng)
        for y in sorted({int(m[:4]) for m in months}):
            ctx.conn.execute(f"""CREATE TABLE IF NOT EXISTS mkt_uk.crime_incident_{y} PARTITION OF mkt_uk.crime_incident
                                 FOR VALUES FROM ('{y}-01-01') TO ('{y + 1}-01-01')""")
            ctx.conn.execute(f"COMMENT ON TABLE mkt_uk.crime_incident_{y} IS 'Partition năm {y}.'")
        start, end = f"{months[0]}-01", f"{months[-1]}-01"
        ctx.sql("xoá các tháng sẽ nạp lại", "DELETE FROM mkt_uk.crime_incident WHERE month BETWEEN %s AND %s",
                (start, end))
        ctx.sql("INSERT crime_incident", f"""
            INSERT INTO mkt_uk.crime_incident (month, crime_ref, reported_by, falls_within, crime_type, lsoa21_code,
                location_desc, last_outcome, geom, release_id)
            SELECT (month || '-01')::date, nullif(crime_id, ''), reported_by, nullif(falls_within, ''), crime_type,
                   nullif(lsoa_code, ''), nullif(location, ''), nullif(last_outcome, ''),
                   CASE WHEN nullif(longitude, '') IS NOT NULL
                        THEN ST_SetSRID(ST_MakePoint(longitude::float8, latitude::float8), 4326) END, %s
            FROM {t}""", (ctx.release_id,))
        n_db = ctx.scalar("SELECT count(*) FROM mkt_uk.crime_incident WHERE month BETWEEN %s AND %s", (start, end))
        ctx.expect("mkt_uk.crime_incident", n_db, total)
        n_default = ctx.scalar("SELECT count(*) FROM mkt_uk.crime_incident_default")
        if n_default:
            raise LoadError(f"Partition crime_incident_default có {n_default} dòng (phải rỗng)")

        # tháng mà lực lượng không gửi dữ liệu → hiển thị "thiếu dữ liệu" thay vì 0 tội phạm
        forces = json.loads((ctx.dir / "forces.json").read_text())
        ctx.sql("tính crime_coverage_gap", """
            WITH present AS (SELECT DISTINCT month, reported_by FROM mkt_uk.crime_incident
                             WHERE month BETWEEN %(start)s AND %(end)s)
            INSERT INTO mkt_uk.crime_coverage_gap (police_force, month, reason)
            SELECT f.name, m.month::date, 'no street-level data in archive ' || %(ver)s
            FROM jsonb_to_recordset(%(forces)s::jsonb) AS f(id text, name text)
            CROSS JOIN generate_series(%(start)s::date, %(end)s::date, interval '1 month') AS m(month)
            LEFT JOIN present p ON p.month = m.month::date AND p.reported_by = f.name
            WHERE p.month IS NULL
            ON CONFLICT (police_force, month) DO UPDATE SET reason = EXCLUDED.reason, detected_at = now()""",
                {"forces": json.dumps(forces), "start": start, "end": end, "ver": ctx.version})
        gaps = ctx.conn.execute("""SELECT police_force, count(*) FROM mkt_uk.crime_coverage_gap
                                   WHERE month BETWEEN %s AND %s GROUP BY 1 ORDER BY 2 DESC""", (start, end)).fetchall()
        if gaps:
            log.warning("    lực lượng thiếu tháng: %s", gaps)
        ctx.conn.execute("ANALYZE mkt_uk.crime_incident")
        ctx.drop_stage("crime")
        return {"rows": total, "months": len(months), "gap_forces": len(gaps)}

