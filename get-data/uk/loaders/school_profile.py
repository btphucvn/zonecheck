"""Hồ sơ trường (England) ngoài kết quả thi: học sinh, vắng học, nơi học sinh đi tiếp, số bài thi theo môn, sĩ số lớp.

- `dfe_school_profile` (DfE Compare School Performance): SEN, vắng học, destinations KS4 / 16-18 / HE, bài thi KS4 theo môn.
- `dfe_spc` (EES Schools, pupils and their characteristics, file cấp trường): sĩ số, giới, FSM, EAL, dân tộc HS,
  sĩ số theo khối, sĩ số lớp.

Giá trị theo trường → core.poi_metric_value (metric subject=poi). TB của LA và England → mkt_uk.school_benchmark
(la_code = mã LA cũ dạng số như trong GIAS "LA (code)", 'ENG' = England; phase = primary/secondary/… hoặc ks).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date

from .base import LoadContext, LoadError, Loader, zip_members
from .metrics import register_metric

log = logging.getLogger(__name__)

BENCH_DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.school_benchmark (
    la_code text NOT NULL,
    phase text NOT NULL,
    metric_id text NOT NULL REFERENCES core.metric (id),
    period date NOT NULL,
    value_num double precision,
    value_json jsonb,
    release_id bigint REFERENCES ops.dataset_release (id),
    PRIMARY KEY (la_code, phase, metric_id, period)
);
COMMENT ON TABLE mkt_uk.school_benchmark IS 'TB chỉ số trường theo LA (mã LA cũ dạng số, như GIAS "LA (code)") và England (la_code = ENG). phase: primary/secondary/special/all hoặc ks2/ks4/ks5 cho kết quả thi.'"""

PV_COLS = ["urn", "metric_id", "period", "value_num", "value_json", "sample_size"]
BM_COLS = ["la_code", "phase", "metric_id", "period", "value_num", "value_json"]
MISSING = {"", "SUPP", "NE", "NA", "NP", "X", "Z", "C", "..", "-", "LOWCOV", "N/A", "DNS", "NEW"}


def num(v):
    if v is None:
        return None
    s = str(v).strip().rstrip("%").replace(",", "")
    if s.upper() in MISSING:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def year_period(label: str) -> date:
    """'2024-2025' hoặc '202526' → ngày kết thúc năm học."""
    m = re.fullmatch(r"(\d{4})-(\d{4})", label)
    if m:
        return date(int(m.group(2)), 7, 31)
    m = re.fullmatch(r"(\d{4})(\d{2})", label)
    if m:
        return date(2000 + int(m.group(2)), 7, 31)
    raise LoadError(f"Không đọc được năm học {label!r}")


def phase_of(text: str) -> str:
    t = (text or "").lower()
    if "special" in t:
        return "special"
    if "independent" in t:
        return "independent"
    if "primary" in t:
        return "primary"
    if "secondary" in t:
        return "secondary"
    return "other"


def ensure_bench(ctx: LoadContext) -> None:
    ctx.conn.execute(BENCH_DDL)


def register(ctx: LoadContext, defs: dict, dataset: str, description: str) -> None:
    """defs: metric_id → (tên, value_type, unit, decimals)."""
    for mid, (name, vt, unit, dec) in defs.items():
        register_metric(ctx, mid, category="education", dataset=dataset, value_type=vt, unit=unit, decimals=dec,
                        direction=0, period_type="year", native_level=None, aggregation="none", scope="uk.england",
                        name=name, scorable=False, description=description)
    ctx.conn.execute("UPDATE core.metric SET subject = 'poi' WHERE id = ANY(%s)", (list(defs),))


def write_poi_values(ctx: LoadContext, name: str, rows: list, metric_ids: list[str], min_match: float = 0.9) -> int:
    """rows (urn, metric_id, period, value_num, value_json, sample_size) → core.poi_metric_value (thay giá trị cũ)."""
    st = ctx.stage_table(name, PV_COLS, {"period": "date", "value_num": "float8", "value_json": "jsonb", "sample_size": "int"})
    ctx.copy_rows(st, PV_COLS, rows, f"COPY {name}")
    total = ctx.scalar(f"SELECT count(DISTINCT urn) FROM {st}")
    matched = ctx.scalar(f"""SELECT count(DISTINCT s.urn) FROM {st} s JOIN core.poi p
        ON p.market_code='uk' AND p.external_scheme='urn' AND p.external_id = s.urn""")
    ratio = matched / total if total else 0
    log.info("    %s: %s/%s URN khớp trường trong GIAS (%.1f%%)", name, matched, total, ratio * 100)
    if ratio < min_match:
        raise LoadError(f"{name}: chỉ {ratio:.1%} URN khớp GIAS")
    ctx.sql(f"xoá giá trị cũ {name}", "DELETE FROM core.poi_metric_value WHERE metric_id = ANY(%s)", (metric_ids,))
    n = ctx.sql(f"ghi {name}", f"""
        INSERT INTO core.poi_metric_value (poi_id, metric_id, period, value_num, value_json, sample_size, release_id)
        SELECT DISTINCT ON (p.id, s.metric_id, s.period) p.id, s.metric_id, s.period, s.value_num, s.value_json,
               s.sample_size, %s
        FROM {st} s JOIN core.poi p ON p.market_code='uk' AND p.external_scheme='urn' AND p.external_id = s.urn
        WHERE s.value_num IS NOT NULL OR s.value_json IS NOT NULL
        ORDER BY p.id, s.metric_id, s.period, s.sample_size DESC NULLS LAST
        ON CONFLICT (poi_id, metric_id, period) DO UPDATE SET value_num = EXCLUDED.value_num,
            value_json = EXCLUDED.value_json, sample_size = EXCLUDED.sample_size, release_id = EXCLUDED.release_id,
            computed_at = now()""", (ctx.release_id,))
    ctx.drop_stage(name)
    return n


def write_benchmarks(ctx: LoadContext, name: str, rows: list, metric_ids: list[str]) -> int:
    ensure_bench(ctx)
    st = ctx.stage_table(name, BM_COLS, {"period": "date", "value_num": "float8", "value_json": "jsonb"})
    ctx.copy_rows(st, BM_COLS, rows, f"COPY {name}")
    ctx.sql(f"xoá TB cũ {name}", "DELETE FROM mkt_uk.school_benchmark WHERE metric_id = ANY(%s)", (metric_ids,))
    n = ctx.sql(f"ghi TB {name}", f"""
        INSERT INTO mkt_uk.school_benchmark (la_code, phase, metric_id, period, value_num, value_json, release_id)
        SELECT DISTINCT ON (la_code, phase, metric_id, period) la_code, phase, metric_id, period, value_num, value_json, %s
        FROM {st} WHERE value_num IS NOT NULL OR value_json IS NOT NULL
        ON CONFLICT (la_code, phase, metric_id, period) DO UPDATE SET value_num = EXCLUDED.value_num,
            value_json = EXCLUDED.value_json, release_id = EXCLUDED.release_id""", (ctx.release_id,))
    ctx.drop_stage(name)
    return n


def weighted_benchmarks(rows: list[tuple], metric_ids: set[str]) -> list[tuple]:
    """rows (la_code, phase, metric_id, period, value, weight) → TB có trọng số theo LA × phase, England × phase, và 'all'."""
    acc = defaultdict(lambda: [0.0, 0.0])
    for la, phase, mid, period, v, w in rows:
        if v is None or not w or mid not in metric_ids:
            continue
        for key in ((la, phase), (la, "all"), ("ENG", phase), ("ENG", "all")):
            a = acc[(*key, mid, period)]
            a[0] += v * w
            a[1] += w
    return [(la, ph, mid, per, round(s / w, 2), None) for (la, ph, mid, per), (s, w) in acc.items() if w > 0]


def check_pct(ctx_label: str, rows: list, idx: int = 3, lo: float = 0, hi: float = 100, max_bad: float = 0.001) -> None:
    vals = [r[idx] for r in rows if r[idx] is not None]
    bad = sum(1 for v in vals if v < lo or v > hi)
    log.info("    ✓ %s: %s giá trị, ngoài [%s, %s]: %s", ctx_label, f"{len(vals):,}", lo, hi, bad)
    if not vals or bad > max_bad * len(vals):
        raise LoadError(f"{ctx_label}: {bad}/{len(vals)} giá trị ngoài [{lo}, {hi}]")


# ================================================================ dfe_school_profile =====
SEN_DEFS = {
    "uk.pupils.sen_ehcp_pct": ("Pupils with an education, health and care (EHC) plan", "percent", "%", 1),
    "uk.pupils.sen_support_pct": ("Pupils receiving SEN support", "percent", "%", 1),
    "uk.pupils.sen_pct": ("Pupils with special educational needs (EHC plan or SEN support)", "percent", "%", 1),
}
ABS_DEFS = {
    "uk.pupils.absence_pct": ("Overall absence (% of sessions missed)", "percent", "%", 1),
    "uk.pupils.persistent_absence_pct": ("Persistently absent pupils (missing 10%+ of sessions)", "percent", "%", 1),
}
DEST_DEFS = {
    "uk.dest.ks4": ("Destinations after key stage 4 (% of pupils, sustained)", "distribution", None, 0),
    "uk.dest.ks5": ("Destinations after 16-18 study (% of students, sustained)", "distribution", None, 0),
    "uk.dest.ks5_he": ("Progression to higher education or training after 16-18 study", "distribution", None, 0),
}
SUBJ_DEFS = {"uk.ks4.subject_entries": ("Key stage 4 entries by subject and qualification", "distribution", None, 0)}

# khoá json → cột file (phần trăm)
KS4_DEST = {"overall": "OVERALL_DESTPER", "education": "EDUCATIONPER", "fe": "FEPER", "school_sixth_form": "SCH_6THPER",
            "sixth_form_college": "SIXTH_COLPER", "other_education": "OTHER_EDUPER", "apprenticeship": "APPRENPER",
            "employment": "EMPLOYMENTPER", "not_sustained": "NOT_SUSTAINEDPER", "unknown": "UNKNOWNPER"}
KS5_DEST = {"overall": "TOT_OVERALLPER", "education": "TOT_EDUCATIONPER", "fe": "TOT_FEPER", "higher_education": "TOT_HEPER",
            "other_education": "TOT_OTHER_EDUPER", "apprenticeship": "TOT_APPRENPER", "employment": "TOT_EMPLOYMENTPER",
            "not_sustained": "TOT_NOT_SUSTAINEDPER", "unknown": "TOT_NOT_CAPTUREDPER"}
KS5_HE = {"progressed": "ALL_PROGRESSED", "higher_education": "ALL_HE", "top_third_he": "ALL_TOP3RD",
          "apprenticeship": "ALL_APPREN", "higher_technical": "ALL_HTECH"}
DEST_FILES = [("ks4dest", "uk.dest.ks4", KS4_DEST, "COHORT", "ks4"), ("ks5dest", "uk.dest.ks5", KS5_DEST, "TOT_COHORT", "ks5"),
              ("ks5desthe", "uk.dest.ks5_he", KS5_HE, "ALL_COHORT", "ks5")]


class SchoolProfileLoader(Loader):
    source = "dfe_school_profile"
    depends_on = ("gias",)
    description = ("DfE theo trường → core.poi_metric_value uk.pupils.* (SEN, vắng học), uk.dest.* (KS4/16-18/HE), "
                   "uk.ks4.subject_entries + TB LA/England → mkt_uk.school_benchmark")

    def load(self, ctx: LoadContext) -> dict:
        defs = {**SEN_DEFS, **ABS_DEFS, **DEST_DEFS, **SUBJ_DEFS}
        register(ctx, defs, "uk.dfe.school_profile", "DfE Compare School Performance, school level")
        stats = {}
        stats.update(self._sen(ctx))
        stats.update(self._absence(ctx))
        stats.update(self._destinations(ctx))
        stats.update(self._subjects(ctx))
        return stats

    # ------------------------------------------------------------------ SEN -----
    def _sen(self, ctx: LoadContext) -> dict:
        f = ctx.file(r"^dfe-census-\d{4}-\d{4}\.csv$")
        period = year_period(re.search(r"(\d{4}-\d{4})", f.name).group(1))
        rows, bench = [], []
        with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                urn, nor = (r.get("URN") or "").strip(), num(r.get("NOR"))
                ehcp, support = num(r.get("PSENELSE")), num(r.get("PSENELK"))
                total = round(ehcp + support, 2) if ehcp is not None and support is not None else None
                vals = {"uk.pupils.sen_ehcp_pct": ehcp, "uk.pupils.sen_support_pct": support, "uk.pupils.sen_pct": total}
                if urn == "NAT":  # dòng England theo phase (PRI/SEC/SPEC…)
                    for mid, v in vals.items():
                        bench.append(("ENG", phase_of(r.get("SCHOOLTYPE")), mid, period, v, None))
                    continue
                if not urn.isdigit():
                    continue
                size = int(nor) if nor else None
                for mid, v in vals.items():
                    rows.append((urn, mid, period, v, None, size))
        if len(rows) < 3 * 20_000:
            raise LoadError(f"Census trường: chỉ {len(rows):,} giá trị (kỳ vọng ~24 nghìn trường × 3)")
        check_pct("SEN %", rows)
        # cross-check: EHC plan TB toàn quốc ~3–6%, SEN support ~12–16% (DfE SEN in England)
        nat = {(b[1], b[2]): b[4] for b in bench}
        e = nat.get(("primary", "uk.pupils.sen_ehcp_pct"))
        s = nat.get(("primary", "uk.pupils.sen_support_pct"))
        log.info("    England tiểu học: EHC plan %s%%, SEN support %s%%", e, s)
        if e is None or s is None or not (1 <= e <= 8 and 8 <= s <= 22):
            raise LoadError(f"TB SEN England bất thường: EHC={e}, support={s} (có thể cột PSENELSE/PSENELK bị đổi nghĩa)")
        n = write_poi_values(ctx, "pupil_sen", rows, list(SEN_DEFS))
        # TB LA: tự tính theo số HS (file chỉ có dòng England)
        la_rows = self._la_weighted(ctx, rows, set(SEN_DEFS))
        nb = write_benchmarks(ctx, "bench_sen", la_rows + bench, list(SEN_DEFS))
        return {"sen_values": n, "sen_benchmarks": nb}

    def _la_weighted(self, ctx: LoadContext, rows: list, mids: set[str]) -> list:
        """Tính TB theo LA × phase từ giá trị trường; LA + phase lấy từ GIAS (attrs) qua URN."""
        urns = sorted({r[0] for r in rows})
        info = dict(((u, (la, ph)) for u, la, ph in ctx.conn.execute("""
            SELECT external_id, attrs->>'LA (code)', coalesce(attrs->>'PhaseOfEducation (name)', '') || ' '
                   || coalesce(attrs->>'EstablishmentTypeGroup (name)', '')
            FROM core.poi WHERE market_code='uk' AND external_scheme='urn' AND external_id = ANY(%s)""", (urns,))))
        src = []
        for urn, mid, period, v, _, size in rows:
            if urn in info and info[urn][0]:
                la, ph = info[urn]
                src.append((la, phase_of(ph), mid, period, v, size))
        return [b for b in weighted_benchmarks(src, mids) if b[0] != "ENG"]

    # -------------------------------------------------------------- absence -----
    def _absence(self, ctx: LoadContext) -> dict:
        f = ctx.file(r"^dfe-absence-\d{4}-\d{4}\.csv$")
        period = year_period(re.search(r"(\d{4}-\d{4})", f.name).group(1))
        rows, bench = [], []
        phase_code = {"PRI": "primary", "SEC": "secondary", "SPEC": "special", "SPE": "special"}
        with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                vals = {"uk.pupils.absence_pct": num(r.get("PERCTOT")),
                        "uk.pupils.persistent_absence_pct": num(r.get("PPERSABS10"))}
                if (r.get("LA") or "").strip() == "NAT":
                    for mid, v in vals.items():
                        bench.append(("ENG", phase_code.get((r.get("ESTAB") or "").strip(), "other"), mid, period, v, None))
                    continue
                urn = (r.get("URN") or "").strip()
                if not urn.isdigit():
                    continue
                for mid, v in vals.items():
                    rows.append((urn, mid, period, v, None, None))
        if len(rows) < 2 * 18_000:
            raise LoadError(f"Vắng học: chỉ {len(rows):,} giá trị")
        check_pct("vắng học %", rows)
        nat = {(b[1], b[2]): b[4] for b in bench}
        pa = nat.get(("secondary", "uk.pupils.persistent_absence_pct"))
        log.info("    England THCS: vắng thường xuyên %s%%", pa)
        if pa is None or not 10 <= pa <= 40:
            raise LoadError(f"TB vắng học thường xuyên THCS bất thường: {pa}")
        n = write_poi_values(ctx, "pupil_absence", rows, list(ABS_DEFS))
        # trọng số LA: số HS từ dfe-census cùng release
        sizes = {}
        with open(ctx.file(r"^dfe-census-\d{4}-\d{4}\.csv$"), encoding="utf-8-sig", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                if (r.get("URN") or "").strip().isdigit() and num(r.get("NOR")):
                    sizes[r["URN"].strip()] = int(num(r["NOR"]))
        rows_w = [(u, m, p, v, j, sizes.get(u)) for u, m, p, v, j, _ in rows]
        nb = write_benchmarks(ctx, "bench_absence", self._la_weighted(ctx, rows_w, set(ABS_DEFS)) + bench, list(ABS_DEFS))
        return {"absence_values": n, "absence_benchmarks": nb}

    # --------------------------------------------------------- destinations -----
    def _destinations(self, ctx: LoadContext) -> dict:
        out = {}
        for prefix, mid, cols, cohort_col, ks in DEST_FILES:
            f = ctx.file(rf"^dfe-{prefix}-\d{{4}}-\d{{4}}\.csv$")
            period = year_period(re.search(r"(\d{4}-\d{4})", f.name).group(1))
            rows, bench, flat = [], [], []
            with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
                rd = csv.DictReader(fh)
                absent = [c for c in [cohort_col, *cols.values()] if c not in (rd.fieldnames or [])]
                if absent:
                    raise LoadError(f"{f.name}: thiếu cột {absent}")
                for r in rd:
                    vals = {k: num(r.get(c)) for k, c in cols.items()}
                    cohort = num(r.get(cohort_col))
                    if all(v is None for v in vals.values()):
                        continue
                    js = json.dumps({"cohort": int(cohort) if cohort else None, **vals})
                    head = vals.get("overall", vals.get("progressed"))
                    rt = (r.get("RECTYPE") or "").strip()
                    if rt == "NAT":
                        bench.append(("ENG", ks, mid, period, head, js))
                    elif rt == "LA":
                        bench.append(((r.get("LEA") or "").strip(), ks, mid, period, head, js))
                    elif (r.get("URN") or "").strip().isdigit():
                        rows.append((r["URN"].strip(), mid, period, head, js, int(cohort) if cohort else None))
                        flat.extend((None, None, None, v) for v in vals.values())
            check_pct(f"{mid} %", flat)
            if len(rows) < 1500:
                raise LoadError(f"{f.name}: chỉ {len(rows)} trường")
            eng = next((b for b in bench if b[0] == "ENG"), None)
            log.info("    %s England: %s", mid, eng[5] if eng else None)
            if eng is None or eng[4] is None or not 30 <= eng[4] <= 100:
                raise LoadError(f"{mid}: dòng England thiếu hoặc bất thường: {eng}")
            out[f"{mid}_values"] = write_poi_values(ctx, f"dest_{prefix}", rows, [mid], min_match=0.85)
            out[f"{mid}_benchmarks"] = write_benchmarks(ctx, f"bench_{prefix}", bench, [mid])
        return out

    # ------------------------------------------------------------- subjects -----
    def _subjects(self, ctx: LoadContext) -> dict:
        import openpyxl
        z = ctx.file(r"^dfe-ks4subjects-\d{4}-\d{4}\.zip$")
        period = year_period(re.search(r"(\d{4}-\d{4})", z.name).group(1))
        members = zip_members(z, r"entriesandgrades.*\.xlsx$")
        if len(members) != 1:
            raise LoadError(f"Cần 1 file entriesandgrades*.xlsx trong {z.name}, thấy {members}")
        # urn → (qual, subject) → {"n": entries, "g": {grade: count}}
        per = defaultdict(lambda: defaultdict(lambda: {"n": 0, "g": {}}))
        bad = Counter()
        with zipfile.ZipFile(z) as zf, zf.open(members[0]) as fh:
            wb = openpyxl.load_workbook(io.BytesIO(fh.read()), read_only=True)
            ws = next((w for w in wb.worksheets if w.title.lower().startswith("institution")), None)
            if ws is None:
                raise LoadError(f"Không thấy sheet Institution_results: {[w.title for w in wb.worksheets]}")
            it = ws.iter_rows(values_only=True)
            head = [str(h or "").strip() for h in next(it)]
            need = ["Unique Reference Number (URN)", "Qualification description", "Subject description", "Grade",
                    "Number of entries at grade"]
            if any(c not in head for c in need):
                raise LoadError(f"Sheet thiếu cột {[c for c in need if c not in head]}: {head}")
            ix = {c: head.index(c) for c in need}
            for row in it:
                urn = row[ix[need[0]]]
                if urn is None:
                    continue
                urn = str(urn).strip().split(".")[0]
                n = row[ix[need[4]]]
                if not isinstance(n, (int, float)):
                    bad[str(n)] += 1
                    continue
                cell = per[urn][(str(row[ix[need[1]]]).strip(), str(row[ix[need[2]]]).strip())]
                grade = str(row[ix[need[3]]]).strip()
                if grade == "Total number entered":
                    cell["n"] = int(n)
                else:
                    cell["g"][grade] = int(n)
            wb.close()
        if bad:
            log.warning("    số bài thi không phải số (bỏ qua): %s", dict(bad.most_common(5)))
        rows = []
        for urn, subj in per.items():
            items = sorted(({"q": q, "s": s, **v} for (q, s), v in subj.items() if v["n"] > 0), key=lambda x: -x["n"])
            if items:
                rows.append((urn, "uk.ks4.subject_entries", period, len(items), json.dumps(items), None))
        if not 3500 <= len(rows) <= 7500:
            raise LoadError(f"Số trường có bài thi KS4 bất thường: {len(rows)}")
        maths = sum(1 for r in rows if '"Mathematics"' in r[4])
        log.info("    %s trường có bài thi KS4, %s có môn Mathematics", len(rows), maths)
        if maths < 0.8 * len(rows):
            raise LoadError(f"Chỉ {maths}/{len(rows)} trường có Mathematics — tên môn đổi?")
        return {"subject_schools": write_poi_values(ctx, "ks4_subjects", rows, list(SUBJ_DEFS), min_match=0.85)}


# =========================================================================== dfe_spc =====
SPC_FILE = r"spc_school_level_underlying_data.*\.csv$"
CLASS_FILE = r"spc_school_level_class_size_underlying_data.*\.csv$"
ETHNIC = {  # khoá → phần tên cột "% of pupils classified as … ethnic origin"
    "white_british": "white British", "irish": "Irish", "traveller_irish": "traveller of Irish heritage",
    "other_white": "any other white background", "gypsy_roma": "Gypsy/Roma",
    "white_black_caribbean": "white and black Caribbean", "white_black_african": "white and black African",
    "white_asian": "white and Asian", "other_mixed": "any other mixed background", "indian": "Indian",
    "pakistani": "Pakistani", "bangladeshi": "Bangladeshi", "other_asian": "any other Asian background",
    "caribbean": "Caribbean", "african": "African", "other_black": "any other black background", "chinese": "Chinese",
    "other": "any other ethnic group",
}
YEARS = ["Nursery 1", "Nursery 2", "Reception", *[f"Year group {i}" for i in range(1, 15)]]
YEAR_KEY = {"Nursery 1": "N1", "Nursery 2": "N2", "Reception": "R", **{f"Year group {i}": f"Y{i}" for i in range(1, 15)}}
SPC_DEFS = {
    "uk.pupils.headcount": ("Number of pupils (school census)", "count", None, 0),
    "uk.pupils.girls_pct": ("Girls (% of pupils)", "percent", "%", 1),
    "uk.pupils.fsm_pct": ("Pupils eligible for free school meals", "percent", "%", 1),
    "uk.pupils.eal_pct": ("Pupils whose first language is not English", "percent", "%", 1),
    "uk.pupils.young_carer_pct": ("Pupils who are young carers", "percent", "%", 1),
    "uk.pupils.ethnicity": ("Pupils by ethnic group (%)", "distribution", None, 0),
    "uk.pupils.year_groups": ("Pupils by year group and sex", "distribution", None, 0),
    "uk.school.class_size_avg": ("Average size of one-teacher classes", "number", None, 1),
    "uk.school.class_size_ks1": ("Average size of key stage 1 classes taught by one teacher", "number", None, 1),
    "uk.school.class_size_ks2": ("Average size of key stage 2 classes taught by one teacher", "number", None, 1),
}
NUM_SPC = ["uk.pupils.headcount", "uk.pupils.girls_pct", "uk.pupils.fsm_pct", "uk.pupils.eal_pct", "uk.pupils.young_carer_pct"]
NUM_CLASS = {"uk.school.class_size_avg": "average size of one teacher classes",
             "uk.school.class_size_ks1": "average size of key stage 1 classes taught by one teacher",
             "uk.school.class_size_ks2": "average size of key stage 2 classes taught by one teacher"}


def _zip_csv(z, pattern: str):
    members = zip_members(z, pattern)
    if len(members) != 1:
        raise LoadError(f"Cần 1 file khớp {pattern} trong {z.name}, thấy {members}")
    zf = zipfile.ZipFile(z)
    return zf, csv.DictReader(io.TextIOWrapper(zf.open(members[0]), encoding="utf-8-sig", errors="replace", newline=""))


class SpcLoader(Loader):
    source = "dfe_spc"
    depends_on = ("gias",)
    description = ("DfE SPC cấp trường → uk.pupils.* (sĩ số, giới, FSM, EAL, dân tộc, khối) + uk.school.class_size_* "
                   "+ TB LA/England → mkt_uk.school_benchmark")

    def load(self, ctx: LoadContext) -> dict:
        register(ctx, SPC_DEFS, "uk.dfe.spc", "DfE Schools, pupils and their characteristics, school-level underlying data")
        z = ctx.file(r"^ees_.*\.zip$")
        rows, src = [], []
        zf, rd = _zip_csv(z, SPC_FILE)
        with zf:
            cols = rd.fieldnames or []
            eth_cols = {}
            for k, label in ETHNIC.items():
                hits = [c for c in cols if c == f"% of pupils classified as {label} ethnic origin"]
                if len(hits) != 1:
                    raise LoadError(f"SPC: không thấy cột dân tộc {label!r}")
                eth_cols[k] = hits[0]
            need = ["urn", "time_period", "headcount of pupils", "headcount total female", "phase_type_grouping",
                    "old_la_code", "% of pupils known to be eligible for free school meals",
                    "% of pupils whose first language is known or believed to be other than English"]
            if any(c not in cols for c in need):
                raise LoadError(f"SPC thiếu cột {[c for c in need if c not in cols]}")
            for r in rd:
                urn = (r.get("urn") or "").strip()
                if not urn.isdigit():
                    continue
                period = year_period(r["time_period"].strip())
                hc = num(r["headcount of pupils"])
                if not hc:
                    continue
                girls = num(r["headcount total female"])
                vals = {
                    "uk.pupils.headcount": hc,
                    "uk.pupils.girls_pct": round(100 * girls / hc, 1) if girls is not None else None,
                    "uk.pupils.fsm_pct": num(r["% of pupils known to be eligible for free school meals"]),
                    "uk.pupils.eal_pct": num(r["% of pupils whose first language is known or believed to be other than English"]),
                    "uk.pupils.young_carer_pct": num(r.get("% of pupils who are a young carer")),
                }
                eth = {k: num(r[c]) for k, c in eth_cols.items()}
                eth["unclassified"] = num(r.get("% of pupils unclassified"))
                yg = {}
                for y in YEARS:
                    f_ = sum(num(r.get(f"{t} female {y}")) or 0 for t in ("full-time", "part-time"))
                    m_ = sum(num(r.get(f"{t} male {y}")) or 0 for t in ("full-time", "part-time"))
                    if f_ or m_:
                        yg[YEAR_KEY[y]] = {"f": int(f_), "m": int(m_)}
                size = int(hc)
                for mid, v in vals.items():
                    rows.append((urn, mid, period, v, None, size))
                if any(v for v in eth.values()):
                    rows.append((urn, "uk.pupils.ethnicity", period, eth.get("white_british"), json.dumps(eth), size))
                if yg:
                    rows.append((urn, "uk.pupils.year_groups", period, size, json.dumps(yg), size))
                la, ph = (r.get("old_la_code") or "").strip(), phase_of(r.get("phase_type_grouping"))
                for mid in ("uk.pupils.girls_pct", "uk.pupils.fsm_pct", "uk.pupils.eal_pct", "uk.pupils.young_carer_pct"):
                    src.append((la, ph, mid, period, vals[mid], size))
        n_schools = len({r[0] for r in rows})
        log.info("    SPC: %s trường", f"{n_schools:,}")
        if not 20_000 <= n_schools <= 30_000:
            raise LoadError(f"SPC: số trường bất thường {n_schools}")
        check_pct("SPC %", [r for r in rows if r[1] != "uk.pupils.headcount" and r[4] is None])
        total = sum(r[3] for r in rows if r[1] == "uk.pupils.headcount")
        log.info("    tổng HS (SPC): %s (DfE công bố ~9,0–9,1 triệu kể cả trường tư)", f"{total:,.0f}")
        if not 8_000_000 <= total <= 10_000_000:
            raise LoadError(f"Tổng HS bất thường: {total:,.0f}")
        eth_bad = [r for r in rows if r[1] == "uk.pupils.ethnicity"
                   and not 90 <= sum(v or 0 for v in json.loads(r[4]).values()) <= 110]
        log.info("    dân tộc HS: %s trường có tổng % lệch khỏi 90–110", len(eth_bad))
        if len(eth_bad) > 0.02 * n_schools:
            raise LoadError(f"Dân tộc HS: {len(eth_bad)} trường có tổng % bất thường")

        # ---- sĩ số lớp
        zf, rd = _zip_csv(z, CLASS_FILE)
        with zf:
            if any(c not in (rd.fieldnames or []) for c in NUM_CLASS.values()):
                raise LoadError(f"File sĩ số lớp thiếu cột {[c for c in NUM_CLASS.values() if c not in rd.fieldnames]}")
            for r in rd:
                urn = (r.get("urn") or "").strip()
                if not urn.isdigit():
                    continue
                period = year_period(r["time_period"].strip())
                pupils = num(r.get("total number of pupils in classes taught by one teacher"))
                for mid, c in NUM_CLASS.items():
                    v = num(r.get(c))
                    if v:  # 0 = không có lớp loại đó
                        rows.append((urn, mid, period, v, None, int(pupils) if pupils else None))
                        src.append(((r.get("old_LA_code") or "").strip(), phase_of(r.get("phase_type_grouping")),
                                    mid, period, v, int(pupils) if pupils else None))
        cs = [r[3] for r in rows if r[1] == "uk.school.class_size_avg"]
        avg = sum(cs) / len(cs) if cs else 0
        log.info("    sĩ số lớp: %s trường, TB %.1f (DfE: tiểu học ~26–27, THCS ~22)", len(cs), avg)
        if len(cs) < 15_000 or not 18 <= avg <= 30 or max(cs) > 60:
            raise LoadError(f"Sĩ số lớp bất thường: n={len(cs)}, TB={avg:.1f}, max={max(cs) if cs else None}")

        n = write_poi_values(ctx, "spc", rows, list(SPC_DEFS))
        bench = weighted_benchmarks(src, set(SPC_DEFS))
        nb = write_benchmarks(ctx, "bench_spc", bench, list(SPC_DEFS))
        return {"schools": n_schools, "values": n, "benchmarks": nb}


SCHOOL_PROFILE_LOADERS = [SchoolProfileLoader(), SpcLoader()]
