"""Tỷ lệ % từ các bảng phân phối Census 2021 → chỉ số số `uk.share.*` ở mọi cấp từ LSOA trở lên.

Bảng Census lưu dạng phân phối (value_num = tổng, value_json = số người/hộ theo nhóm, khoá phân cấp "Cha: Con").
Tách thành chỉ số % riêng để có phân vị toàn quốc (điểm 1–10), bản đồ theo từng nhóm và xếp hạng, giống cách
CrystalRoof trình bày (nhóm nghề NS-SeC 5 lớp, 7 bậc học vấn, 16 nhóm dân tộc, 9 tôn giáo, tuổi 20 năm, 7 loại hộ).

Mỗi chỉ số = Σ(nhóm tử số) / Σ(nhóm mẫu số) × 100. Mẫu số mặc định là tổng các nhóm lá của bảng (không dùng
value_num vì một số bảng có nhóm "không áp dụng"). Dân tộc và tôn giáo: sensitivity = 'sensitive', không tính điểm.
"""
from __future__ import annotations

import json
import logging
from datetime import date

from ..loaders.base import LoadContext, LoadError
from ..loaders.metrics import register_metric
from .base import Step

log = logging.getLogger(__name__)

PERIOD = date(2021, 3, 21)
LEVELS = ["lsoa", "msoa", "sector", "district", "postal_area", "town", "ward", "lad", "region", "nation"]

# metric key → (bảng, [khoá tử số], tên, nhóm chỉ số, direction, sensitive)
# Mẫu số = tổng các khoá trong DENOM của bảng.
ETH = "uk.census21.ts021"
REL = "uk.census21.ts030"
AGE = "uk.census21.ts007a"
HH = "uk.census21.ts003"
TEN = "uk.census21.ts054"
SEC = "uk.census21.ts062"
QUAL = "uk.census21.ts067"

AGE_KEYS = {"0_4": "Aged 4 years and under", **{f"{a}_{a + 4}": f"Aged {a} to {a + 4} years" for a in range(5, 85, 5)},
            "85p": "Aged 85 years and over"}


def ages(lo: int, hi: int | None) -> list[str]:
    out = []
    for k, label in AGE_KEYS.items():
        start = 0 if k == "0_4" else (85 if k == "85p" else int(k.split("_")[0]))
        if start >= lo and (hi is None or start < hi):
            out.append(label)
    return out


DENOM = {
    ETH: ["White: English, Welsh, Scottish, Northern Irish or British", "White: Irish", "White: Gypsy or Irish Traveller",
          "White: Roma", "White: Other White", "Mixed or Multiple ethnic groups", "Asian, Asian British or Asian Welsh",
          "Black, Black British, Black Welsh, Caribbean or African", "Other ethnic group"],
    REL: ["No religion", "Christian", "Buddhist", "Hindu", "Jewish", "Muslim", "Sikh", "Other religion", "Not answered"],
    AGE: list(AGE_KEYS.values()),
    HH: ["One person household", "Single family household", "Other household types"],
    TEN: ["Owned", "Shared ownership", "Social rented", "Private rented", "Lives rent free"],
    SEC: ["L1, L2 and L3 Higher managerial, administrative and professional occupations",
          "L4, L5 and L6 Lower managerial, administrative and professional occupations", "L7 Intermediate occupations",
          "L8 and L9 Small employers and own account workers", "L10 and L11 Lower supervisory and technical occupations",
          "L12 Semi-routine occupations", "L13 Routine occupations", "L14.1 and L14.2 Never worked and long-term unemployed",
          "L15 Full-time students"],
    QUAL: ["No qualifications", "Level 1 and entry level qualifications", "Level 2 qualifications", "Apprenticeship",
           "Level 3 qualifications", "Level 4 qualifications and above", "Other qualifications"],
}

A, P = "Asian, Asian British or Asian Welsh", "Black, Black British, Black Welsh, Caribbean or African"
SHARES: dict[str, tuple[str, list[str], str, str, int, bool]] = {
    # ---- nghề (NS-SeC gộp 5 lớp như CrystalRoof)
    "managerial_professional": (SEC, DENOM[SEC][0:2], "Managerial and professional occupations", "economy", 1, False),
    "intermediate_occupations": (SEC, DENOM[SEC][2:4], "Intermediate occupations, small employers and own account workers", "economy", 0, False),
    "routine_manual": (SEC, DENOM[SEC][4:7], "Routine and manual occupations", "economy", 0, False),
    "never_worked": (SEC, DENOM[SEC][7:8], "Never worked or long-term unemployed", "economy", -1, False),
    "fulltime_students": (SEC, DENOM[SEC][8:9], "Full-time students (aged 16+)", "economy", 0, False),
    # ---- học vấn (16+)
    "degree": (QUAL, ["Level 4 qualifications and above"], "Degree level or above (Level 4+)", "economy", 1, False),
    "alevels": (QUAL, ["Level 3 qualifications"], "A levels or equivalent (Level 3)", "economy", 0, False),
    "apprenticeship": (QUAL, ["Apprenticeship"], "Apprenticeship", "economy", 0, False),
    "gcses": (QUAL, ["Level 2 qualifications"], "5+ GCSEs or equivalent (Level 2)", "economy", 0, False),
    "some_gcses": (QUAL, ["Level 1 and entry level qualifications"], "1–4 GCSEs or entry level (Level 1)", "economy", 0, False),
    "no_qualifications": (QUAL, ["No qualifications"], "No qualifications", "economy", -1, False),
    "other_qualifications": (QUAL, ["Other qualifications"], "Other qualifications (vocational, foreign)", "economy", 0, False),
    # ---- tenure (hộ)
    "owned": (TEN, ["Owned", "Shared ownership"], "Owner-occupied homes (incl. shared ownership)", "housing", 0, False),
    "owned_outright": (TEN, ["Owned: Owns outright"], "Owned outright", "housing", 0, False),
    "private_rented": (TEN, ["Private rented", "Lives rent free"], "Privately rented homes", "housing", 0, False),
    "social_rented": (TEN, ["Social rented"], "Socially rented homes", "housing", 0, False),
    # ---- tuổi (20 năm)
    "age_under20": (AGE, ages(0, 20), "Aged under 20", "people", 0, False),
    "age_20_39": (AGE, ages(20, 40), "Aged 20 to 39", "people", 0, False),
    "age_40_59": (AGE, ages(40, 60), "Aged 40 to 59", "people", 0, False),
    "age_60_79": (AGE, ages(60, 80), "Aged 60 to 79", "people", 0, False),
    "age_80p": (AGE, ages(80, None), "Aged 80 and over", "people", 0, False),
    # ---- loại hộ (7 nhóm như CrystalRoof)
    "hh_alone": (HH, ["One person household"], "People living alone", "people", 0, False),
    "hh_couple_no_children": (HH, ["Single family household: Married or civil partnership couple: No children",
                                   "Single family household: Cohabiting couple family: No children"],
                              "Couples without children", "people", 0, False),
    "hh_dependent_children": (HH, ["Single family household: Married or civil partnership couple: Dependent children",
                                   "Single family household: Cohabiting couple family: With dependent children",
                                   "Single family household: Lone parent family: With dependent children"],
                              "Families with dependent children", "people", 0, False),
    "hh_adult_children": (HH, ["Single family household: Married or civil partnership couple: All children non-dependent",
                               "Single family household: Cohabiting couple family: All children non-dependent",
                               "Single family household: Lone parent family: All children non-dependent"],
                          "Families with adult children at home", "people", 0, False),
    "hh_aged_66p": (HH, ["Single family household: All aged 66 years and over"], "Families all aged 66 and over", "people", 0, False),
    "hh_other_family": (HH, ["Single family household: Other single family household"], "Other family households", "people", 0, False),
    "hh_shared": (HH, ["Other household types"], "Shared, multi-family or student households", "people", 0, False),
    "hh_lone_parent": (HH, ["Single family household: Lone parent family: With dependent children"],
                       "Lone parents with dependent children", "people", 0, False),
    # ---- dân tộc (16 nhóm như CrystalRoof) — nhạy cảm
    "eth_white_british": (ETH, ["White: English, Welsh, Scottish, Northern Irish or British"], "White British", "people", 0, True),
    "eth_white_irish": (ETH, ["White: Irish"], "White Irish", "people", 0, True),
    "eth_gypsy": (ETH, ["White: Gypsy or Irish Traveller"], "Gypsy or Irish Traveller", "people", 0, True),
    "eth_roma": (ETH, ["White: Roma"], "Roma", "people", 0, True),
    "eth_other_white": (ETH, ["White: Other White"], "Other White", "people", 0, True),
    "eth_mixed": (ETH, ["Mixed or Multiple ethnic groups"], "Mixed or multiple ethnic groups", "people", 0, True),
    "eth_indian": (ETH, [f"{A}: Indian"], "Indian", "people", 0, True),
    "eth_pakistani": (ETH, [f"{A}: Pakistani"], "Pakistani", "people", 0, True),
    "eth_bangladeshi": (ETH, [f"{A}: Bangladeshi"], "Bangladeshi", "people", 0, True),
    "eth_chinese": (ETH, [f"{A}: Chinese"], "Chinese", "people", 0, True),
    "eth_other_asian": (ETH, [f"{A}: Other Asian"], "Other Asian", "people", 0, True),
    "eth_black_african": (ETH, [f"{P}: African"], "Black African", "people", 0, True),
    "eth_black_caribbean": (ETH, [f"{P}: Caribbean"], "Black Caribbean", "people", 0, True),
    "eth_other_black": (ETH, [f"{P}: Other Black"], "Other Black", "people", 0, True),
    "eth_arab": (ETH, ["Other ethnic group: Arab"], "Arab", "people", 0, True),
    "eth_other": (ETH, ["Other ethnic group: Any other ethnic group"], "Any other ethnic group", "people", 0, True),
    # ---- tôn giáo — nhạy cảm
    "rel_none": (REL, ["No religion"], "No religion", "people", 0, True),
    "rel_christian": (REL, ["Christian"], "Christian", "people", 0, True),
    "rel_muslim": (REL, ["Muslim"], "Muslim", "people", 0, True),
    "rel_hindu": (REL, ["Hindu"], "Hindu", "people", 0, True),
    "rel_sikh": (REL, ["Sikh"], "Sikh", "people", 0, True),
    "rel_jewish": (REL, ["Jewish"], "Jewish", "people", 0, True),
    "rel_buddhist": (REL, ["Buddhist"], "Buddhist", "people", 0, True),
    "rel_other": (REL, ["Other religion"], "Other religion", "people", 0, True),
    "rel_not_stated": (REL, ["Not answered"], "Religion not stated", "people", 0, True),
}
GROUPS_SUM_TO_100 = {  # các nhóm phải cộng lại ≈ 100% (kiểm tra mapping khoá)
    "occupation": [k for k, v in SHARES.items() if v[0] == SEC],
    "qualification": [k for k in ("degree", "alevels", "apprenticeship", "gcses", "some_gcses", "no_qualifications", "other_qualifications")],
    "age": [k for k in SHARES if k.startswith("age_")],
    "household": ["hh_alone", "hh_couple_no_children", "hh_dependent_children", "hh_adult_children", "hh_aged_66p",
                  "hh_other_family", "hh_shared"],
    "ethnicity": [k for k in SHARES if k.startswith("eth_")],
    "religion": [k for k in SHARES if k.startswith("rel_")],
    "tenure": ["owned", "private_rented", "social_rented"],
}


class CensusShares(Step):
    name = "census_shares"
    depends_on = ("rollup",)
    needs_sources = ("census2021",)
    description = "Tỷ lệ % từ phân phối Census 2021 (nghề, học vấn, tenure, tuổi, loại hộ, dân tộc, tôn giáo) → uk.share.*"

    def run(self, ctx: LoadContext) -> dict:
        # kiểm tra mọi khoá có trong dữ liệu (tên nhóm Nomis đổi → dừng, không âm thầm ra 0%)
        for ts in {v[0] for v in SHARES.values()}:
            keys = {r[0] for r in ctx.conn.execute("""SELECT DISTINCT jsonb_object_keys(v.value_json) FROM core.metric_value v
                JOIN core.geo_area a ON a.id = v.area_id AND a.level_code = 'lad'
                WHERE v.market_code='uk' AND v.metric_id = %s""", (ts,))}
            need = set(DENOM[ts]) | {k for v in SHARES.values() if v[0] == ts for k in v[1]}
            missing = need - keys
            if missing:
                raise LoadError(f"{ts}: thiếu nhóm {sorted(missing)} (Nomis đổi tên nhóm?)")

        defs = []
        for key, (ts, num, name, cat, direction, sensitive) in SHARES.items():
            register_metric(ctx, f"uk.share.{key}", category=cat, dataset="uk.ons.census2021", value_type="percent", unit="%",
                            decimals=1, direction=direction, period_type="snapshot", native_level="lsoa",
                            aggregation="weighted_mean", scope="uk.ew", name=f"{name} (% {'of households' if ts in (HH, TEN) else 'of residents'})",
                            sensitivity="sensitive" if sensitive else "normal", scorable=False,
                            description=f"Census 2021 {ts.rsplit('.', 1)[1].upper()}: share in group")
            defs.append((f"uk.share.{key}", ts, num, DENOM[ts]))
        ctx.conn.execute("CREATE TEMP TABLE share_def (metric_id text, ts text, num text[], den text[]) ON COMMIT DROP")
        ctx.copy_rows("share_def", ["metric_id", "ts", "num", "den"],
                      [(m, ts, "{" + ",".join(json.dumps(k) for k in n) + "}", "{" + ",".join(json.dumps(k) for k in d) + "}")
                       for m, ts, n, d in defs], "COPY định nghĩa tỷ lệ")
        ids = [d[0] for d in defs]
        ctx.sql("xoá giá trị cũ", "DELETE FROM core.metric_value WHERE market_code='uk' AND metric_id = ANY(%s)", (ids,))
        n = ctx.sql("tính tỷ lệ", """
            INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size)
            SELECT 'uk', v.area_id, d.metric_id, %s, round((100 * x.num / x.den)::numeric, 2), x.den::int
            FROM share_def d
            JOIN core.metric_value v ON v.market_code='uk' AND v.metric_id = d.ts AND v.value_json IS NOT NULL
            JOIN core.geo_area a ON a.id = v.area_id AND a.level_code = ANY(%s)
            CROSS JOIN LATERAL (
                SELECT (SELECT coalesce(sum((v.value_json->>k)::float8), 0) FROM unnest(d.num) k) AS num,
                       (SELECT coalesce(sum((v.value_json->>k)::float8), 0) FROM unnest(d.den) k) AS den) x
            WHERE x.den >= 10""", (PERIOD, LEVELS))

        # ---- kiểm tra: mỗi nhóm cộng lại ≈ 100%, giá trị trong [0, 100], England & Wales hợp lý
        ctx.check_range("tỷ lệ Census", "core.metric_value v", "v.value_num", 0, 100,
                        where="v.market_code='uk' AND v.metric_id LIKE 'uk.share.%%'")
        nat = dict(ctx.conn.execute("""SELECT v.metric_id, v.value_num FROM core.metric_value v
            JOIN core.geo_area a ON a.id = v.area_id AND a.level_code = 'nation' AND a.code = 'E92000001'
            WHERE v.metric_id LIKE 'uk.share.%%'""").fetchall())
        for g, keys in GROUPS_SUM_TO_100.items():
            s = sum(nat.get(f"uk.share.{k}", 0) for k in keys)
            log.info("    England %s: tổng %.1f%%", g, s)
            if not 98.5 <= s <= 101.5:
                raise LoadError(f"Nhóm {g} cộng lại {s:.1f}% ở England (kỳ vọng ~100%) — sai khoá Census")
        # số công bố Census 2021 England: Level 4+ 33,9%; White British 73,5%; sở hữu 62,3%; xã hội 17,1%
        for k, lo, hi in (("degree", 32, 36), ("eth_white_british", 72, 75), ("owned", 61, 64), ("social_rented", 16, 18.5)):
            v = nat.get(f"uk.share.{k}")
            log.info("    England %s = %s%%", k, v)
            if v is None or not lo <= v <= hi:
                raise LoadError(f"England uk.share.{k} = {v} ngoài [{lo}, {hi}] so với số ONS công bố")
        return {"values": n, "metrics": len(ids)}
