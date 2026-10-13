"""Nạp Wales: WIMD 2025 → core.metric_value (LSOA); danh sách trường Wales → làm giàu/bổ sung core.poi."""
from __future__ import annotations

import json
import logging
from datetime import date

from .base import LoadContext, LoadError, Loader, slug_sql
from .metrics import MV_COLS, insert_values, mv_stage, register_metric

log = logging.getLogger(__name__)

WIMD_DOMAINS = [  # (tên cột trong file, id, tên hiển thị)
    ("WIMD 2025", "overall", "Welsh Index of Multiple Deprivation"),
    ("Income", "income", "Income deprivation (WIMD)"),
    ("Employment", "employment", "Employment deprivation (WIMD)"),
    ("Health", "health", "Health deprivation (WIMD)"),
    ("Education", "education", "Education deprivation (WIMD)"),
    ("Access to Services", "access", "Access to services deprivation (WIMD)"),
    ("Housing", "housing", "Housing deprivation (WIMD)"),
    ("Community Safety", "safety", "Community safety deprivation (WIMD)"),
    ("Physical Environment", "environment", "Physical environment deprivation (WIMD)"),
]
WALES_LSOA = 1917


def _read_sheet(path, sheet: str, header_first_col: str):
    """Đọc sheet ODS, tự tìm dòng header (dòng có ô đầu = header_first_col)."""
    import pandas as pd
    raw = pd.read_excel(path, engine="odf", sheet_name=sheet, header=None)
    idx = raw.index[raw.iloc[:, 0].astype(str).str.strip() == header_first_col]
    if len(idx) != 1:
        raise LoadError(f"{path.name}/{sheet}: không tìm được dòng header '{header_first_col}'")
    df = raw.iloc[idx[0] + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[idx[0]]]
    return df[df[header_first_col].astype(str).str.match(r"^W0\d{7}$")]


class WimdLoader(Loader):
    source = "wimd"
    depends_on = ("boundaries_lsoa21",)
    description = "WIMD 2025 → metric uk.wimd25.<domain>_{score,rank} + overall_decile theo LSOA Wales"

    def load(self, ctx: LoadContext) -> dict:
        ranks = _read_sheet(ctx.file(r"ranks.*\.ods$"), "WIMD_2025_ranks", "LSOA code")
        deciles = _read_sheet(ctx.file(r"ranks.*\.ods$"), "Deciles_quintiles_quartiles", "LSOA code")
        scores = _read_sheet(ctx.file(r"scores.*\.ods$"), "Data", "LSOA code")
        for name, df in (("ranks", ranks), ("scores", scores), ("deciles", deciles)):
            if len(df) != WALES_LSOA or df["LSOA code"].nunique() != WALES_LSOA:
                raise LoadError(f"WIMD {name}: {len(df)} dòng / {df['LSOA code'].nunique()} mã, cần {WALES_LSOA}")
            missing = [c for c, *_ in WIMD_DOMAINS if name != "deciles" and c not in df.columns]
            if missing:
                raise LoadError(f"WIMD {name}: thiếu cột {missing} (có {list(df.columns)})")
        period = date(2025, 1, 1)
        rows = []
        for col, key, _ in WIMD_DOMAINS:
            for code, v in zip(ranks["LSOA code"], ranks[col]):
                rows.append(("lsoa", code, f"uk.wimd25.{key}_rank", period, float(v), None))
            for code, v in zip(scores["LSOA code"], scores[col]):
                rows.append(("lsoa", code, f"uk.wimd25.{key}_score", period, float(v), None))
        dcol = next(c for c in deciles.columns if "overall decile" in c.lower())
        for code, v in zip(deciles["LSOA code"], deciles[dcol]):
            rows.append(("lsoa", code, "uk.wimd25.overall_decile", period, float(v), None))

        common = dict(category="economy", dataset="uk.welsh_gov.wimd", period_type="snapshot", native_level="lsoa",
                      scope="uk.wales")
        for col, key, name in WIMD_DOMAINS:
            register_metric(ctx, f"uk.wimd25.{key}_score", value_type="index", decimals=2, direction=-1,
                            name=f"{name} score", **common)
            register_metric(ctx, f"uk.wimd25.{key}_rank", value_type="rank", direction=1,
                            name=f"{name} rank (1 = most deprived)", scorable=False, **common)
        register_metric(ctx, "uk.wimd25.overall_decile", value_type="rank", direction=1,
                        name="WIMD 2025 decile (1 = most deprived 10%)", scorable=False, **common)

        t = mv_stage(ctx, "mv_wimd")
        ctx.copy_rows(t, MV_COLS, rows, "COPY WIMD values")
        # ---- kiểm tra hợp lý
        for col, key, _ in WIMD_DOMAINS:
            mid = f"uk.wimd25.{key}_rank"
            ctx.check_range(mid, t, "value_num", 1, WALES_LSOA, where=f"metric_id = '{mid}'")
            distinct = ctx.scalar(f"SELECT count(DISTINCT value_num) FROM {t} WHERE metric_id = %s", (mid,))
            if distinct < WALES_LSOA * 0.99:  # hạng phải gần như là hoán vị 1..1917
                raise LoadError(f"{mid}: chỉ {distinct} hạng khác nhau / {WALES_LSOA}")
            ctx.check_range(f"uk.wimd25.{key}_score", t, "value_num", 0, 100,
                            where=f"metric_id = 'uk.wimd25.{key}_score'")
        ctx.check_range("uk.wimd25.overall_decile", t, "value_num", 1, 10, where="metric_id = 'uk.wimd25.overall_decile'")
        # hạng tổng và điểm tổng phải ngược chiều (điểm cao = thiếu thốn = hạng nhỏ)
        corr = ctx.scalar(f"""SELECT corr(r.value_num, s.value_num) FROM {t} r JOIN {t} s ON s.code = r.code
                              AND s.metric_id = 'uk.wimd25.overall_score' WHERE r.metric_id = 'uk.wimd25.overall_rank'""")
        if corr is None or corr > -0.8:
            raise LoadError(f"Tương quan hạng–điểm WIMD bất thường: {corr} (kỳ vọng < -0.8)")
        log.info("    ✓ tương quan hạng–điểm WIMD tổng: %.3f", corr)
        n, unmatched = insert_values(ctx, t, "WIMD 2025")
        if unmatched:
            raise LoadError(f"WIMD: {unmatched} giá trị không khớp LSOA trong DB")
        ctx.drop_stage("mv_wimd")
        return {"values": n, "rank_score_corr": round(corr, 3)}


SECTOR_TYPE = {"Primary": "school.primary", "Secondary": "school.secondary", "Middle": "school.all_through",
               "Special": "school.special", "Nursery": "school.nursery"}
WS_COLS = ["school_number", "name", "la_code", "la_name", "sector", "governance", "language", "school_type",
           "religious", "address", "postcode", "phone", "pupils", "category"]


class WalesSchoolsLoader(Loader):
    source = "wales_schools"
    depends_on = ("gias", "onspd")
    description = ("Danh sách trường Wales → cập nhật cấp học/ngôn ngữ cho trường Wales trong GIAS (ghép LA+mã cơ sở); "
                   "trường không có trong GIAS → thêm POI mới (scheme wales_school, toạ độ theo postcode)")

    def load(self, ctx: LoadContext) -> dict:
        import pandas as pd
        f = ctx.file(r"\.ods$")
        sheets = pd.read_excel(f, engine="odf", sheet_name=["Maintained", "Independent", "PRU"])
        rows = []
        for cat, df in sheets.items():
            if "School Number" not in df.columns:
                raise LoadError(f"Sheet {cat}: thiếu cột 'School Number' (có {list(df.columns)})")
            for _, r in df.iterrows():
                num = str(r["School Number"]).strip().split(".")[0]
                if not num.isdigit():
                    continue
                g = lambda k: (None if k not in df.columns or pd.isna(r[k]) else str(r[k]).strip())  # noqa: E731
                addr = ", ".join(x for x in (g("Address 1"), g("Address 2"), g("Address 3"), g("Address 4")) if x)
                pupils = g("Pupils - see notes")
                rows.append((num, g("School Name"), num[:3], g("Local Authority"),
                             g("Sector") or ("Independent" if cat == "Independent" else "PRU"),
                             g("Governance - see notes"), g("School Language Category - see notes"), g("School Type"),
                             g("Religious Character"), addr or None, g("Postcode"), g("Phone Number"),
                             pupils if pupils and pupils.replace(".", "").isdigit() else None, cat))
        n_src = len(rows)
        if not 1300 <= n_src <= 2000:
            raise LoadError(f"Số trường Wales bất thường: {n_src} (kỳ vọng 1.300–2.000)")
        bad_sector = {r[4] for r in rows if r[13] == "Maintained" and r[4] not in SECTOR_TYPE}
        if bad_sector:
            raise LoadError(f"Sector chưa ánh xạ: {bad_sector}")
        t = ctx.stage_table("wales_schools", WS_COLS)
        ctx.copy_rows(t, WS_COLS, rows, "COPY danh sách trường Wales")
        ctx.conn.execute(f"CREATE INDEX ON {t} (school_number)")

        type_case = "CASE s.sector " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in SECTOR_TYPE.items()) + \
                    " ELSE 'school.other' END"
        wattrs = """jsonb_strip_nulls(jsonb_build_object('wales_school_number', s.school_number, 'wales_sector', s.sector,
                    'governance', s.governance, 'language_category', s.language, 'wales_school_type', s.school_type,
                    'religious_character', nullif(s.religious, '---'), 'pupils', s.pupils, 'wales_category', s.category))"""
        gias_match = """p.market_code = 'uk' AND p.external_scheme = 'urn'
                        AND p.attrs->>'EstablishmentTypeGroup (name)' = 'Welsh schools' AND p.status <> 'closed'
                        AND (p.attrs->>'LA (code)') || lpad(p.attrs->>'EstablishmentNumber', 4, '0') = s.school_number"""
        if not ctx.scalar("SELECT count(*) FROM core.poi WHERE external_scheme='urn' AND attrs ? 'LA (code)'"):
            raise LoadError("GIAS trong DB chưa có 'LA (code)' trong attrs — nạp lại gias (bản mới) trước")
        matched = ctx.sql("làm giàu trường Wales trong GIAS", f"""
            UPDATE core.poi p SET type_code = {type_case}, attrs = p.attrs || {wattrs}
            FROM {t} s WHERE {gias_match}""")
        ratio = matched / n_src
        log.info("    ghép được %s/%s trường Wales với GIAS (%.1f%%)", matched, n_src, ratio * 100)
        if ratio < 0.9:
            sample = ctx.conn.execute(f"""SELECT s.school_number, s.name FROM {t} s WHERE NOT EXISTS
                (SELECT 1 FROM core.poi p WHERE {gias_match}) LIMIT 5""").fetchall()
            raise LoadError(f"Chỉ ghép được {ratio:.1%} trường Wales với GIAS (cần ≥ 90%), ví dụ chưa ghép: {sample}")
        inserted = ctx.sql("thêm trường Wales không có trong GIAS", f"""
            INSERT INTO core.poi (market_code, type_code, external_scheme, external_id, name, slug, geom, address,
                                  postal_code, area_id, status, attrs, dataset_id, release_id)
            SELECT 'uk', {type_case}, 'wales_school', s.school_number, s.name,
                   'w' || s.school_number || '-' || {slug_sql('s.name')}, pc.geom, s.address, s.postcode, pc.area_id,
                   'open', {wattrs}, 'uk.welsh_gov.schools', %s
            FROM {t} s JOIN mkt_uk.postcode pc ON pc.postcode = s.postcode AND pc.geom IS NOT NULL
            WHERE NOT EXISTS (SELECT 1 FROM core.poi p WHERE {gias_match})
            ON CONFLICT (market_code, external_scheme, external_id) DO UPDATE SET name = EXCLUDED.name,
                type_code = EXCLUDED.type_code, geom = EXCLUDED.geom, address = EXCLUDED.address,
                postal_code = EXCLUDED.postal_code, area_id = EXCLUDED.area_id, attrs = EXCLUDED.attrs,
                status = 'open', release_id = EXCLUDED.release_id""", (ctx.release_id,))
        left = n_src - matched - inserted
        if left > 0.02 * n_src:
            raise LoadError(f"{left} trường Wales không ghép GIAS và không có postcode hợp lệ (> 2%)")
        dist = dict(ctx.conn.execute("""SELECT type_code, count(*) FROM core.poi WHERE status <> 'closed'
            AND (attrs ? 'wales_sector') GROUP BY 1 ORDER BY 2 DESC""").fetchall())
        log.info("    phân bố loại trường Wales sau cập nhật: %s", dist)
        ctx.stats["rows_in_file"] = n_src
        ctx.drop_stage("wales_schools")
        return {"schools": n_src, "matched_gias": matched, "inserted": inserted, "unplaced": left,
                "types": json.loads(json.dumps(dist))}
