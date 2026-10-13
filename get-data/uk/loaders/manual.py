"""Nạp nguồn tải tay: Ofcom Connected Nations (broadband OA → LSOA, di động LA) và số bệnh nhân GP (NHS England)."""
from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from datetime import date

from .base import LoadContext, LoadError, Loader, zip_members
from .metrics import MV_COLS, insert_values, mv_stage, num, register_metric

log = logging.getLogger(__name__)

# metric → (cột số lượng trong file OA "res" (nhà ở), tên, hướng)
BB_METRICS = {
    "uk.bb.gigabit_pct": ("Number of premises with Gigabit availability", "Homes with gigabit broadband available", 1),
    "uk.bb.ufbb_pct": ("Number of premises with UFBB availability", "Homes with ultrafast broadband (300 Mbit/s+)", 1),
    "uk.bb.sfbb_pct": ("Number of premises with SFBB availability", "Homes with superfast broadband (30 Mbit/s+)", 1),
    "uk.bb.no_decent_pct": ("Number of premises unable to receive decent broadband from fixed or FWA",
                            "Homes without decent broadband (under 10 Mbit/s)", -1),
}
BB_TOTAL = "All Premises"
# metric → (hàm lấy % từ dòng file LA, tên). Cột *_N = % nhà/khu có sóng từ đúng N nhà mạng (N = 0..4)
MOBILE_METRICS = {
    "uk.mobile.4g_indoor_all": (lambda r: _pct(r, "4G_prem_in_4"), "Homes with indoor 4G from all operators"),
    "uk.mobile.4g_outdoor_all": (lambda r: _pct(r, "4G_prem_out_4"), "Homes with outdoor 4G from all operators"),
    "uk.mobile.voice_indoor_all": (lambda r: _pct(r, "Voice_prem_in_4"), "Homes with indoor voice coverage from all operators"),
    "uk.mobile.5g_outdoor_any": (lambda r: _any(r, "5G_high_confidence_prem_out"), "Homes with outdoor 5G from at least one operator"),
}


def _pct(r: dict, col: str):
    if col not in r:
        raise LoadError(f"File di động Ofcom thiếu cột {col}")
    v = num(r[col])
    # ô trống nghĩa là 0% khi các mức khác của cùng nhóm có dữ liệu
    if v is None and any(num(r.get(f"{col[:-2]}_{i}")) is not None for i in range(5)):
        return 0.0
    return v


def _any(r: dict, prefix: str):
    vals = [num(r.get(f"{prefix}_{i}")) for i in range(1, 5)]
    if all(v is None for v in vals) and num(r.get(f"{prefix}_0")) is None:
        return None
    return min(100.0, sum(v or 0 for v in vals))


def _open_csv(z: zipfile.ZipFile, member: str):
    return csv.DictReader(io.TextIOWrapper(z.open(member), encoding="utf-8-sig", newline=""))


class OfcomLoader(Loader):
    source = "ofcom_connected_nations"
    depends_on = ("boundaries_oa21", "boundaries_lsoa21", "boundaries_lad")
    description = "Ofcom: % nhà có gigabit/ultrafast/superfast/thiếu broadband theo OA + LSOA; sóng di động theo LA"

    def load(self, ctx: LoadContext) -> dict:
        y, m = ctx.version.split("-")
        period = date(int(y), int(m), 1)
        fixed = ctx.file(r"_fixed_broadband_coverage.*\.zip$")
        mobile = ctx.file(r"_mobile_coverage.*\.zip$")

        # ---------- broadband: OA (file "res" = chỉ nhà ở) → stage có số lượng để cộng lên LSOA chính xác
        member = zip_members(fixed, r"_fixed_oa_res_coverage_r\d+\.csv$")
        if len(member) != 1:
            raise LoadError(f"Cần đúng 1 file *_fixed_oa_res_coverage_*.csv trong {fixed.name}, thấy {member}")
        cols = [BB_TOTAL] + [c for c, _, _ in BB_METRICS.values()]
        oa = ctx.stage_table("ofcom_oa", ["oa", *cols], {c: "float8" for c in cols})
        bad_pct = 0
        with zipfile.ZipFile(fixed) as z:
            rd = _open_csv(z, member[0])
            missing = [c for c in ["output_area", *cols] if c not in rd.fieldnames]
            if missing:
                raise LoadError(f"{member[0]}: thiếu cột {missing}")

            def rows():
                nonlocal bad_pct
                for r in rd:
                    if not re.fullmatch(r"[EW]00\d{6}", r["output_area"]):
                        continue  # Scotland, Bắc Ireland: không có ranh giới OA trong DB
                    vals = [num(r[c]) for c in cols]
                    # đối chiếu % công bố với số lượng/tổng (phát hiện đổi định nghĩa mẫu số)
                    tot, giga = vals[0], vals[1]
                    pct = num(r["Gigabit availability (% premises)"])
                    if tot and pct is not None and abs(giga * 100 / tot - pct) > 1.5:
                        bad_pct += 1
                    yield [r["output_area"], *vals]
            n_oa = ctx.copy_rows(oa, ["oa", *cols], rows(), f"COPY {member[0].split('/')[-1]} (E+W)")
        if not 188_000 <= n_oa <= 189_500:
            raise LoadError(f"Số OA E+W trong file Ofcom bất thường: {n_oa:,} (kỳ vọng ~188.880)")
        if bad_pct > n_oa * 0.01:
            raise LoadError(f"{bad_pct:,} OA có % gigabit lệch số lượng/tổng > 1,5 điểm: mẫu số đã đổi?")
        log.info("    %s OA có %% công bố lệch số lượng/tổng > 1,5 điểm (cho phép < 1%%)", bad_pct)
        over = ctx.scalar(f"""SELECT count(*) FROM {oa} WHERE {" OR ".join(f'"{c}" > "{BB_TOTAL}"' for c, _, _ in BB_METRICS.values())}""")
        if over:
            raise LoadError(f"{over} OA có số nhà đạt chuẩn > tổng số nhà")

        t = mv_stage(ctx, "mv_ofcom")
        for mid, (col, _, _) in BB_METRICS.items():
            ctx.sql(f"OA {mid}", f"""INSERT INTO {t} (level, code, metric_id, period, value_num)
                SELECT 'oa', oa, %s, %s, round(("{col}" * 100 / "{BB_TOTAL}")::numeric, 1) FROM {oa} WHERE "{BB_TOTAL}" > 0""",
                    (mid, period))
            ctx.sql(f"LSOA {mid}", f"""INSERT INTO {t} (level, code, metric_id, period, value_num)
                SELECT 'lsoa', l.code, %s, %s, round((sum(o."{col}") * 100 / sum(o."{BB_TOTAL}"))::numeric, 1)
                FROM {oa} o JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='oa' AND a.code = o.oa
                JOIN core.geo_area_link k ON k.child_id = a.id
                JOIN core.geo_area l ON l.id = k.parent_id AND l.level_code = 'lsoa'
                GROUP BY l.code HAVING sum(o."{BB_TOTAL}") > 0""", (mid, period))
        n_lsoa = ctx.scalar(f"SELECT count(DISTINCT code) FROM {t} WHERE level='lsoa'")
        if n_lsoa < 35_000:
            raise LoadError(f"Chỉ {n_lsoa:,} LSOA có dữ liệu broadband (kỳ vọng ~35.672): liên kết OA→LSOA thiếu?")

        # ---------- di động: LA + quốc gia
        members = zip_members(mobile, r"_mobile_coverage_laua_r\d+\.csv$")
        if len(members) != 1:
            raise LoadError(f"Cần đúng 1 file *_mobile_coverage_laua_*.csv trong {mobile.name}, thấy {members}")
        mob_rows = []
        with zipfile.ZipFile(mobile) as z:
            for r in _open_csv(z, members[0]):
                code = (r.get("laua") or "").strip()
                if not re.fullmatch(r"[EW]0[6-9]\d{6}", code):
                    continue
                for mid, (fn, _) in MOBILE_METRICS.items():
                    v = fn(r)
                    if v is not None:
                        mob_rows.append(("lad", code, mid, period, v, None))
        n_la = len({r[1] for r in mob_rows})
        if not 300 <= n_la <= 340:
            raise LoadError(f"Số LA E+W trong file di động bất thường: {n_la}")
        ctx.copy_rows(t, MV_COLS, mob_rows, "COPY di động theo LA")

        # ---------- đăng ký + kiểm tra
        for mid, (_, name, direction) in BB_METRICS.items():
            register_metric(ctx, mid, category="connectivity", dataset="uk.ofcom.connected_nations", value_type="percent",
                            unit="%", decimals=1, direction=direction, period_type="snapshot", native_level="oa",
                            aggregation="weighted_mean", scope="uk.ew", name=name,
                            description="Ofcom Connected Nations, residential premises")
        for mid, (_, name) in MOBILE_METRICS.items():
            register_metric(ctx, mid, category="connectivity", dataset="uk.ofcom.connected_nations", value_type="percent",
                            unit="%", decimals=1, direction=1, period_type="snapshot", native_level="lad",
                            aggregation="none", scope="uk.ew", name=name, scorable=False,
                            description="Ofcom Connected Nations, mobile coverage by local authority (premises)")
        ctx.conn.execute(f"ANALYZE {t}")
        ctx.check_range("% broadband + di động", t, "value_num", 0, 100)
        g, s, nd = ctx.conn.execute(f"""SELECT sum("{BB_METRICS['uk.bb.gigabit_pct'][0]}") * 100 / sum("{BB_TOTAL}"),
                                              sum("{BB_METRICS['uk.bb.sfbb_pct'][0]}") * 100 / sum("{BB_TOTAL}"),
                                              sum("{BB_METRICS['uk.bb.no_decent_pct'][0]}") * 100 / sum("{BB_TOTAL}")
                                       FROM {oa}""").fetchone()
        log.info("    E+W (nhà ở): gigabit %.1f%%, superfast %.1f%%, thiếu broadband tử tế %.2f%%", g, s, nd)
        # Ofcom công bố (UK, 2025–26): gigabit ~85–90%, superfast ~97–98%, không đạt 10 Mbit/s < 1%
        if not (70 <= g <= 98 and 93 <= s <= 100 and nd < 2):
            raise LoadError(f"Phủ broadband E+W bất thường: gigabit {g:.1f}%, superfast {s:.1f}%, thiếu {nd:.2f}%")

        def la(mid, code):
            return ctx.scalar(f"SELECT value_num FROM {t} WHERE level='lad' AND metric_id=%s AND code=%s", (mid, code))
        isl, pow_ = la("uk.mobile.4g_indoor_all", "E09000019"), la("uk.mobile.4g_indoor_all", "W06000023")
        log.info("    4G trong nhà đủ mọi nhà mạng: Islington %s%% vs Powys %s%%", isl, pow_)
        if isl is None or pow_ is None or isl <= pow_:
            raise LoadError(f"Kiểm tra định hướng di động thất bại: Islington {isl} không cao hơn Powys {pow_}")
        n, unmatched = insert_values(ctx, t, "Ofcom")
        if unmatched > n * 0.002:
            raise LoadError(f"{unmatched} giá trị Ofcom không khớp mã khu")
        ctx.drop_stage("mv_ofcom", "ofcom_oa")
        return {"values": n, "oa": n_oa, "lsoa": n_lsoa, "la": n_la, "gigabit_ew_pct": round(g, 1)}


class GpPatientsLoader(Loader):
    source = "nhs_gp_patients"
    depends_on = ("nhs_ods",)
    description = "NHS England: số bệnh nhân đăng ký → core.poi.attrs.registered_patients của GP (health.gp)"

    def load(self, ctx: LoadContext) -> dict:
        z = ctx.file(r"gp-reg-pat-prac-all-\d{4}-\d{2}\.zip$")
        members = zip_members(z, r"\.csv$")
        if len(members) != 1:
            raise LoadError(f"Cần đúng 1 CSV trong {z.name}, thấy {members}")
        cols = ["PUBLICATION", "EXTRACT_DATE", "TYPE", "CODE", "POSTCODE", "SEX", "AGE", "NUMBER_OF_PATIENTS"]
        t = ctx.stage_table("gp_patients", cols)
        with zipfile.ZipFile(z) as zf:
            rd = _open_csv(zf, members[0])
            missing = [c for c in cols if c not in rd.fieldnames]
            if missing:
                raise LoadError(f"{members[0]}: thiếu cột {missing}")
            n = ctx.copy_rows(t, cols, ([r[c] for c in cols] for r in rd), f"COPY {members[0]}")
        ctx.check_values_in("TYPE", t, "\"TYPE\"", ["GP"])
        ctx.check_values_in("SEX/AGE", t, "\"SEX\" || '/' || \"AGE\"", ["ALL/ALL"])
        dup = ctx.scalar(f'SELECT count(*) - count(DISTINCT "CODE") FROM {t}')
        if dup:
            raise LoadError(f"{dup} mã practice trùng")
        ctx.check_range("bệnh nhân / practice", t, '"NUMBER_OF_PATIENTS"::int', 0, 200_000)
        if not 5_500 <= n <= 7_500:
            raise LoadError(f"Số practice bất thường: {n} (England ~6.200)")
        total = ctx.scalar(f'SELECT sum("NUMBER_OF_PATIENTS"::bigint) FROM {t}')
        log.info("    %s practice, tổng %s bệnh nhân đăng ký", f"{n:,}", f"{total:,}")
        if not 58_000_000 <= total <= 70_000_000:  # England ~63–65 triệu (cao hơn dân số do đăng ký trùng/chưa xoá)
            raise LoadError(f"Tổng bệnh nhân bất thường: {total:,}")
        extract = ctx.scalar(f'SELECT max("EXTRACT_DATE") FROM {t}')

        ctx.sql("xoá số liệu cũ", """UPDATE core.poi SET attrs = attrs - 'registered_patients' - 'registered_patients_as_of'
                                     WHERE market_code='uk' AND type_code='health.gp' AND attrs ? 'registered_patients'""")
        upd = ctx.sql("ghi registered_patients", f"""
            UPDATE core.poi p SET attrs = p.attrs || jsonb_build_object('registered_patients', s."NUMBER_OF_PATIENTS"::int,
                                                                          'registered_patients_as_of', s."EXTRACT_DATE")
            FROM {t} s WHERE p.market_code='uk' AND p.external_scheme='ods' AND p.external_id = s."CODE"
              AND p.type_code = 'health.gp'""")
        unmatched = n - upd
        log.info("    ghép được %s/%s practice với POI GP", f"{upd:,}", f"{n:,}")
        if upd < n * 0.97:
            raise LoadError(f"Chỉ ghép được {upd}/{n} practice với core.poi (nhs_ods cũ?)")
        ctx.drop_stage("gp_patients")
        return {"practices": n, "matched_poi": upd, "unmatched": unmatched, "total_patients": total,
                "extract_date": extract}
