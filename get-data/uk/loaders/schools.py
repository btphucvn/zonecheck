"""Nạp kết quả thi DfE (KS2/KS4/KS5) → core.metric (subject=poi) + core.poi_metric_value theo URN."""
from __future__ import annotations

import csv
import logging
import re
from collections import Counter
from datetime import date

from .base import LoadContext, LoadError, Loader
from .metrics import register_metric
from .school_profile import write_benchmarks

log = logging.getLogger(__name__)

# (file ks, cột nguồn, metric id, tên, value_type, unit, decimals, direction, khoảng hợp lý lo..hi, cột cỡ mẫu)
DFE_METRICS = [
    ("ks2", "PTRWM_EXP", "uk.ks2.rwm_expected_pct", "KS2: % reaching expected standard in reading, writing & maths", "percent", "%", 0, 1, 0, 100, "TELIG"),
    ("ks2", "PTRWM_HIGH", "uk.ks2.rwm_higher_pct", "KS2: % achieving higher standard in reading, writing & maths", "percent", "%", 0, 1, 0, 100, "TELIG"),
    ("ks2", "READ_AVERAGE", "uk.ks2.reading_score", "KS2: average scaled score in reading", "number", None, 0, 1, 80, 120, "TELIG"),
    ("ks2", "MAT_AVERAGE", "uk.ks2.maths_score", "KS2: average scaled score in maths", "number", None, 0, 1, 80, 120, "TELIG"),
    ("ks2", "READPROG", "uk.ks2.reading_progress", "KS2: reading progress score", "index", None, 1, 1, -30, 30, "TELIG"),
    ("ks2", "WRITPROG", "uk.ks2.writing_progress", "KS2: writing progress score", "index", None, 1, 1, -30, 30, "TELIG"),
    ("ks2", "MATPROG", "uk.ks2.maths_progress", "KS2: maths progress score", "index", None, 1, 1, -30, 30, "TELIG"),
    ("ks4", "ATT8SCR", "uk.ks4.attainment8", "KS4: Attainment 8 score", "number", None, 1, 1, 0, 90, "TPUP"),
    ("ks4", "P8MEA", "uk.ks4.progress8", "KS4: Progress 8 score", "index", None, 2, 1, -7, 7, "TPUP"),
    ("ks4", "PTL2BASICS_94", "uk.ks4.eng_maths_4plus_pct", "KS4: % grade 4+ in English & maths", "percent", "%", 0, 1, 0, 100, "TPUP"),
    ("ks4", "PTL2BASICS_95", "uk.ks4.eng_maths_5plus_pct", "KS4: % grade 5+ in English & maths", "percent", "%", 0, 1, 0, 100, "TPUP"),
    ("ks4", "EBACCAPS", "uk.ks4.ebacc_aps", "KS4: EBacc average point score", "number", None, 2, 1, 0, 9, "TPUP"),
    ("ks4", "PTEBACC_E_PTQ_EE", "uk.ks4.ebacc_entry_pct", "KS4: % of pupils entering the English Baccalaureate", "percent", "%", 0, 1, 0, 100, "TPUP"),
    ("ks5", "TALLPPE_ALEV_1618", "uk.ks5.alevel_aps", "16-18: average point score per A level entry", "number", None, 2, 1, 0, 60, "TPUP1618"),
    ("ks5", "TB3PTSE", "uk.ks5.best3_aps", "16-18: average point score of best 3 A levels", "number", None, 2, 1, 0, 60, "TINCLUDE_B3"),
    ("ks5", "PTAAB_2FAC", "uk.ks5.aab_pct", "16-18: % achieving AAB or better at A level (2+ facilitating subjects)", "percent", "%", 1, 1, 0, 100, "TINCLUDE_AAB_2FAC"),
]
GRADE_COLS = [("ks5", "TALLPPEGRD_ALEV_1618", "uk.ks5.alevel_grade", "16-18: average A level grade"),
              ("ks5", "TB3PTSE_GRD", "uk.ks5.best3_grade", "16-18: average grade of best 3 A levels")]
# dòng TB trong file DfE: LA (có LEA, không URN) và England trường công
LA_RECTYPE = {"ks2": "3", "ks4": "4", "ks5": "4"}
NAT_RECTYPE = {"ks2": "5", "ks4": "7", "ks5": "7"}
SCHOOL_RECTYPES = {"1", "2", "3"}   # 1 trường thường, 2 trường đặc biệt/độc lập, 3 consortium 16+ (có URN)
GRADE_RE = re.compile(r"^(A\*|[A-E])[+-]?$|^U$")
SUPPRESSED = {"SUPP", "LOWCOV"}                       # bị ẩn do mẫu nhỏ / độ phủ thấp → is_suppressed
NOT_AVAILABLE = {"", "NE", "NA", "NP", "NEW", "DNS", "NEWAC", "N/A", "X"}   # không có số liệu → bỏ qua
PV_COLS = ["urn", "metric_id", "period", "value_num", "value_json", "sample_size", "is_suppressed"]


def _num(v: str):
    return float(v.strip().rstrip("%"))


class DfePerformanceLoader(Loader):
    source = "dfe_performance"
    depends_on = ("gias",)
    description = "DfE KS2/KS4/KS5 nhiều năm → core.poi_metric_value (trường theo URN), kiểm tra khoảng giá trị"

    def load(self, ctx: LoadContext) -> dict:
        files = ctx.files(r"^dfe-ks\d-\d{4}-\d{4}\.csv$")
        if not files:
            raise LoadError("Không có file dfe-ks?-YYYY-YYYY.csv")
        rows, odd, missing_cols, years, bench = [], Counter(), {}, [], []
        for path in files:
            m = re.match(r"dfe-(ks\d)-((\d{4})-(\d{4}))\.csv$", path.name)
            ks, ylabel = m.group(1), m.group(2)
            period = date(int(m.group(4)), 7, 31)  # kết thúc năm học
            if ylabel not in years:
                years.append(ylabel)
            with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
                rd = csv.DictReader(f)
                cols = rd.fieldnames or []
                defs = [d for d in DFE_METRICS if d[0] == ks]
                absent = [d[1] for d in defs if d[1] not in cols]
                if absent:
                    missing_cols[f"{ylabel}/{ks}"] = absent
                for r in rd:
                    rt, urn = (r.get("RECTYPE") or "").strip(), (r.get("URN") or "").strip()
                    if not urn.isdigit():
                        la = (r.get("LEA") or "").strip()
                        target = la if rt == LA_RECTYPE[ks] and la else ("ENG" if rt == NAT_RECTYPE[ks] else None)
                        if target:
                            for _, col, mid, *_rest in defs:
                                raw = (r.get(col) or "").strip()
                                try:
                                    bench.append((target, ks, mid, period, _num(raw), None))
                                except ValueError:
                                    pass
                            for gks, gcol, gmid, _ in GRADE_COLS:
                                g = (r.get(gcol) or "").strip() if gks == ks else ""
                                if GRADE_RE.match(g):
                                    bench.append((target, ks, gmid, period, None, f'{{"grade": "{g}"}}'))
                        continue
                    if rt not in SCHOOL_RECTYPES:
                        continue
                    for _, col, mid, *_rest in defs:
                        if col not in cols:
                            continue
                        raw = (r.get(col) or "").strip()
                        size = (r.get(_rest[-1]) or "").strip()
                        size = int(size) if size.isdigit() else None
                        if raw.upper() in NOT_AVAILABLE:
                            continue
                        if raw.upper() in SUPPRESSED:
                            rows.append((urn, mid, period, None, None, size, True))
                            continue
                        try:
                            rows.append((urn, mid, period, _num(raw), None, size, False))
                        except ValueError:
                            odd[(col, raw)] += 1
                    for gks, gcol, gmid, _ in GRADE_COLS:
                        if gks != ks or gcol not in cols:
                            continue
                        g = (r.get(gcol) or "").strip()
                        if GRADE_RE.match(g):
                            rows.append((urn, gmid, period, None, f'{{"grade": "{g}"}}', None, False))
                        elif g and g.upper() not in NOT_AVAILABLE | SUPPRESSED:
                            odd[(gcol, g)] += 1
        zips = files
        if missing_cols:
            log.warning("    cột không có trong một số năm (chỉ số đó bỏ qua năm đó): %s", missing_cols)
        if odd:
            log.warning("    giá trị lạ (bỏ qua): %s", dict(odd.most_common(15)))
        # quá nhiều giá trị lạ → định dạng nguồn đã đổi → dừng
        if sum(odd.values()) > 0.005 * max(len(rows), 1):
            raise LoadError(f"Quá nhiều giá trị không đọc được ({sum(odd.values())}) so với {len(rows)} — định dạng DfE đổi?")

        for ks, col, mid, name, vt, unit, dec, direction, lo, hi, _ in DFE_METRICS:
            register_metric(ctx, mid, category="education", dataset="uk.dfe.school_performance", value_type=vt,
                            unit=unit, decimals=dec, direction=direction, period_type="year", native_level=None,
                            scope="uk.england", name=name, description=f"DfE performance tables, cột {col}")
        for _, _, gmid, gname in GRADE_COLS:
            register_metric(ctx, gmid, category="education", dataset="uk.dfe.school_performance",
                            value_type="category", period_type="year", scope="uk.england", name=gname, scorable=False)
        ctx.conn.execute("UPDATE core.metric SET subject = 'poi' WHERE id LIKE 'uk.ks_.%' AND subject <> 'poi'")

        t = ctx.stage_table("dfe_perf", PV_COLS, {"period": "date", "value_num": "float8", "value_json": "jsonb",
                                                  "sample_size": "int", "is_suppressed": "boolean"})
        n = ctx.copy_rows(t, PV_COLS, rows, f"COPY kết quả {len(zips)} năm")
        # ---- kiểm tra hợp lý từng chỉ số (vi phạm → rollback)
        for ks, col, mid, name, vt, unit, dec, direction, lo, hi, _ in DFE_METRICS:
            if ctx.scalar(f"SELECT count(*) FROM {t} WHERE metric_id = %s", (mid,)):
                ctx.check_range(mid, t, "value_num", lo, hi, where=f"metric_id = '{mid}'")
        latest = max(r[2] for r in rows)
        for mid, min_ratio in (("uk.ks2.rwm_expected_pct", 0.9), ("uk.ks4.attainment8", 0.9)):
            ctx.check_not_null_ratio(f"{mid} năm mới nhất", t, "value_num", min_ratio,
                                     where=f"metric_id = '{mid}' AND period = '{latest}' AND NOT is_suppressed")
        # số trường có kết quả năm mới nhất phải hợp lý (England có ~15k trường tiểu học, ~3,5–4,5k THCS có KS4)
        n_ks2 = ctx.scalar(f"SELECT count(DISTINCT urn) FROM {t} WHERE metric_id='uk.ks2.rwm_expected_pct' AND period=%s", (latest,))
        n_ks4 = ctx.scalar(f"SELECT count(DISTINCT urn) FROM {t} WHERE metric_id='uk.ks4.attainment8' AND period=%s", (latest,))
        if not (12000 <= n_ks2 <= 18000 and 3000 <= n_ks4 <= 6000):
            raise LoadError(f"Số trường năm {latest} bất thường: KS2={n_ks2}, KS4={n_ks4}")
        log.info("    ✓ số trường năm %s: KS2=%s, KS4=%s", latest, n_ks2, n_ks4)

        unmatched = ctx.scalar(f"""SELECT count(DISTINCT urn) FROM {t} s WHERE NOT EXISTS (SELECT 1 FROM core.poi p
                                   WHERE p.market_code='uk' AND p.external_scheme='urn' AND p.external_id = s.urn)""")
        total_urn = ctx.scalar(f"SELECT count(DISTINCT urn) FROM {t}")
        log.info("    URN không có trong GIAS (trường đã đóng/không toạ độ): %s/%s", unmatched, total_urn)
        if unmatched > 0.05 * total_urn:
            raise LoadError(f"{unmatched}/{total_urn} URN không khớp GIAS (> 5%) — kiểm tra lại GIAS")
        ctx.sql("upsert core.poi_metric_value", f"""
            INSERT INTO core.poi_metric_value (poi_id, metric_id, period, value_num, value_json, sample_size,
                                               is_suppressed, release_id)
            SELECT DISTINCT ON (p.id, s.metric_id, s.period)
                   p.id, s.metric_id, s.period, s.value_num, s.value_json, s.sample_size, s.is_suppressed, %s
            FROM {t} s JOIN core.poi p ON p.market_code='uk' AND p.external_scheme='urn' AND p.external_id = s.urn
            ORDER BY p.id, s.metric_id, s.period, s.is_suppressed
            ON CONFLICT (poi_id, metric_id, period) DO UPDATE SET value_num = EXCLUDED.value_num,
                value_json = EXCLUDED.value_json, sample_size = EXCLUDED.sample_size,
                is_suppressed = EXCLUDED.is_suppressed, release_id = EXCLUDED.release_id, computed_at = now()""",
                (ctx.release_id,))
        n_db = ctx.scalar("SELECT count(*) FROM core.poi_metric_value WHERE release_id = %s", (ctx.release_id,))
        expected = ctx.scalar(f"""SELECT count(DISTINCT (p.id, s.metric_id, s.period)) FROM {t} s JOIN core.poi p
                                  ON p.market_code='uk' AND p.external_scheme='urn' AND p.external_id = s.urn""")
        ctx.expect("core.poi_metric_value DfE", n_db, expected)
        ctx.drop_stage("dfe_perf")
        # ---- TB LA / England trường công (dòng tổng trong file DfE)
        eng = {(b[2], b[3]): b[4] for b in bench if b[0] == "ENG"}
        a8 = eng.get(("uk.ks4.attainment8", max(r[2] for r in rows)))
        log.info("    TB England năm mới nhất: Attainment 8 = %s, %s dòng TB LA/England", a8, len(bench))
        if a8 is None or not 35 <= a8 <= 55 or len({b[0] for b in bench}) < 140:
            raise LoadError(f"Dòng TB LA/England bất thường: A8 England={a8}, số LA={len({b[0] for b in bench})}")
        nb = write_benchmarks(ctx, "bench_perf", bench, [d[2] for d in DFE_METRICS] + [g[2] for g in GRADE_COLS])
        return {"years": sorted(years), "values": n_db, "rows_parsed": n, "unmatched_urn": unmatched,
                "odd_values": sum(odd.values()), "benchmarks": nb}
