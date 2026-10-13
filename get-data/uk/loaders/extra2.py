"""Loader đợt 2 (DATA_GAP_TRACKER.md): GP Patient Survey, DWP Universal Credit, HMLR CCOD/OCOD + Registered Leases."""
from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from datetime import date

from .base import LoadContext, LoadError, Loader, zip_members
from .gap_tables import _ddl, _set_subject_poi
from .metrics import register_metric

log = logging.getLogger(__name__)


# -------------------------------------------------------- GP Patient Survey -----
# biến GPPS → (metric, tên). ".pcteval" = tỉ lệ trả lời tích cực (Good / Easy / Yes...) trên người có ý kiến
GPPS = {
    "overallexp": ("uk.gp.overall_good", "Patients rating their overall experience of the GP practice as good"),
    "gpcontactoverall": ("uk.gp.contact_good", "Patients rating their experience of contacting the practice as good"),
    "localgpservicesphone": ("uk.gp.phone_easy", "Patients finding it easy to contact the practice by phone"),
    "localgpserviceswebsite": ("uk.gp.website_easy", "Patients finding the practice website easy to use"),
    "localgpservicesreception": ("uk.gp.reception_helpful", "Patients finding reception and admin staff helpful"),
    "lastgpapptneeds": ("uk.gp.needs_met", "Patients whose needs were met at their last appointment"),
    "lastgpapptconf": ("uk.gp.confidence_trust", "Patients with confidence and trust in the professional they saw"),
}
GPPS_MIN_BASE = 10  # GPPS tự ẩn (-97) khi quá ít phản hồi; thêm ngưỡng cho chắc


class GpPatientSurveyLoader(Loader):
    source = "gp_patient_survey"
    depends_on = ("nhs_ods",)
    description = "GP Patient Survey theo phòng khám → core.poi_metric_value uk.gp.* (% tích cực) cho POI health.gp (mã ODS)"

    def load(self, ctx: LoadContext) -> dict:
        path = ctx.file(r"Practice_data.*\.csv$")
        period = date(int(ctx.version), 1, 1)
        rows = []
        with open(path, encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f)
            miss = [c for v in GPPS for c in (f"{v}.pcteval", f"{v}.baseevaluw") if c not in r.fieldnames]
            if miss or "ad_practicecode" not in r.fieldnames:
                raise LoadError(f"GPPS CSV thiếu cột: {miss}")
            for row in r:
                code = (row["ad_practicecode"] or "").strip().upper()
                if not re.fullmatch(r"[A-Z]\d{5}", code):
                    continue
                for var, (mid, _) in GPPS.items():
                    try:
                        pct, base = float(row[f"{var}.pcteval"]), float(row[f"{var}.baseevaluw"] or 0)
                    except ValueError:
                        continue
                    if pct < 0 or base < GPPS_MIN_BASE:  # -97/-99 = ẩn
                        continue
                    rows.append((code, mid, round(pct * 100, 1), int(base)))
                try:
                    rows.append((code, "uk.gp.survey_responses", float(row["received"]), None))
                except (KeyError, ValueError):
                    pass
        practices = {r[0] for r in rows}
        if not 5500 <= len(practices) <= 7000:
            raise LoadError(f"Số phòng khám GPPS bất thường: {len(practices)}")
        st = ctx.stage_table("gpps", ["ods", "metric_id", "value", "base"], {"value": "float8", "base": "int"})
        ctx.copy_rows(st, ["ods", "metric_id", "value", "base"], rows, "COPY GPPS")
        ctx.check_range("% tích cực", st, "value", 0, 100, where="metric_id <> 'uk.gp.survey_responses'")
        # GPPS 2025 toàn quốc: ~74% đánh giá tốt về tổng thể; trung bình theo phòng khám phải gần đó
        avg = ctx.scalar(f"SELECT avg(value) FROM {st} WHERE metric_id = 'uk.gp.overall_good'")
        log.info("    trung bình 'overall good' theo phòng khám: %.1f%%", avg)
        if not 60 <= avg <= 85:
            raise LoadError(f"Trung bình 'overall good' bất thường: {avg:.1f}%")
        for i, (mid, name) in enumerate([*GPPS.values(), ("uk.gp.survey_responses", "GP Patient Survey responses received")]):
            pct = mid != "uk.gp.survey_responses"
            register_metric(ctx, mid, category="amenities", dataset="uk.nhs.gpps", value_type="percent" if pct else "count",
                            unit="%" if pct else None, decimals=1 if pct else 0, direction=1 if pct else 0,
                            period_type="year", native_level=None, aggregation="none", scope="uk.england", name=name,
                            scorable=False, sort=i,
                            description="GP Patient Survey (NHS England / Ipsos), weighted practice-level results")
        ids = [m for m, _ in GPPS.values()] + ["uk.gp.survey_responses"]
        _set_subject_poi(ctx, ids)
        ctx.sql("xoá giá trị cùng kỳ", "DELETE FROM core.poi_metric_value WHERE metric_id = ANY(%s) AND period = %s",
                (ids, period))
        n = ctx.sql("INSERT poi_metric_value GPPS", f"""
            INSERT INTO core.poi_metric_value (poi_id, metric_id, period, value_num, sample_size, release_id)
            SELECT DISTINCT ON (p.id, s.metric_id) p.id, s.metric_id, %s, s.value, s.base, %s
            FROM {st} s JOIN core.poi p ON p.market_code='uk' AND p.external_scheme='ods' AND p.external_id = s.ods
                                       AND p.type_code = 'health.gp'
            ORDER BY p.id, s.metric_id, p.status = 'open' DESC""", (period, ctx.release_id))
        matched = ctx.scalar(f"""SELECT count(DISTINCT s.ods) FROM {st} s JOIN core.poi p ON p.market_code='uk'
            AND p.external_scheme='ods' AND p.external_id = s.ods AND p.type_code = 'health.gp'""")
        log.info("    %s/%s phòng khám khớp POI GP (mã ODS)", matched, len(practices))
        if matched < 0.9 * len(practices):
            raise LoadError(f"Chỉ {matched}/{len(practices)} phòng khám GPPS khớp POI GP")
        ctx.drop_stage("gpps")
        return {"practices": len(practices), "matched": matched, "values": n, "avg_overall_good": round(avg, 1)}


# ------------------------------------------------------ DWP Universal Credit -----
UC_METRICS = {
    "uk.benefit.uc_rate": ("People on Universal Credit per 100 residents aged 16–64", "s.total"),
    "uk.benefit.uc_not_working_rate": ("People on Universal Credit not in work per 100 residents aged 16–64", "s.not_working"),
}


class UniversalCreditLoader(Loader):
    source = "dwp_uc"
    depends_on = ("ons_lsoa_population",)
    description = "DWP Stat-Xplore UC theo LSOA → uk.benefit.uc_rate, uc_not_working_rate (/100 dân 16–64), uc_working_share"

    def load(self, ctx: LoadContext) -> dict:
        y, m = map(int, ctx.version.split("-"))
        period = date(y, m, 1)
        st = ctx.stage_table("uc", ["lsoa", "band", "people"], {"people": "float8"})
        with open(ctx.file(r"^uc_people_lsoa\.csv$"), newline="") as f:
            r = csv.reader(f)
            if next(r) != ["lsoa21", "employment", "people"]:
                raise LoadError("Header uc_people_lsoa.csv đổi")
            ctx.copy_rows(st, ["lsoa", "band", "people"], ((a, b, float(c or 0)) for a, b, c in r), "COPY UC")
        ctx.check_values_in("nhóm việc làm", st, "band", ["not_working", "working", "unknown"])
        ctx.check_range("số người/LSOA", st, "people", 0, 3000)
        # dân 16–64 kỳ mới nhất (ONS mid-year theo LSOA, value_json có nhóm tuổi)
        ctx.sql("gộp theo LSOA + dân 16–64", f"""
            CREATE TEMP TABLE uc_lsoa ON COMMIT DROP AS
            SELECT a.id AS area_id, s.lsoa, sum(s.people) total,
                   sum(s.people) FILTER (WHERE s.band = 'not_working') not_working,
                   sum(s.people) FILTER (WHERE s.band = 'working') working,
                   (v.value_json->>'16-64')::float8 AS pop1664
            FROM {st} s JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='lsoa' AND a.code = s.lsoa
            LEFT JOIN core.metric_value v ON v.market_code = 'uk' AND v.area_id = a.id AND v.metric_id = 'uk.pop.mid_year'
                 AND v.period = (SELECT max(period) FROM core.metric_value WHERE market_code = 'uk' AND metric_id = 'uk.pop.mid_year')
            GROUP BY a.id, s.lsoa, v.value_json""")
        n_lsoa, n_pop = ctx.conn.execute("SELECT count(*), count(pop1664) FROM uc_lsoa").fetchone()
        ctx.expect("LSOA có dân 16–64", n_pop, n_lsoa, tolerance=0.01)
        rate = ctx.scalar("SELECT 100 * sum(total) / sum(pop1664) FROM uc_lsoa WHERE pop1664 > 0")
        log.info("    E&W: %.1f người UC / 100 dân 16–64", rate)
        if not 10 <= rate <= 30:
            raise LoadError(f"Tỉ lệ UC E&W bất thường: {rate:.1f}/100")
        # định hướng: Blackpool cao hơn Wokingham
        bp, wk = (ctx.scalar("""SELECT 100 * sum(u.total) / sum(u.pop1664) FROM uc_lsoa u
                    WHERE u.lsoa IN (SELECT DISTINCT lsoa21_code FROM mkt_uk.postcode WHERE lad_code = %s)""", (c,))
                  for c in ("E06000009", "E06000041"))
        log.info("    Blackpool %.1f, Wokingham %.1f / 100", bp or 0, wk or 0)
        if not (bp and wk and bp > 2 * wk):
            raise LoadError(f"Kiểm tra định hướng thất bại: Blackpool {bp}, Wokingham {wk}")
        desc = "DWP Stat-Xplore People on Universal Credit (residence-based, LSOA 2021) ÷ ONS mid-year population aged 16–64"
        for mid, (name, _) in UC_METRICS.items():
            register_metric(ctx, mid, category="people", dataset="uk.dwp.uc_people", value_type="number", unit="per 100",
                            decimals=1, direction=-1, period_type="month", native_level="lsoa", aggregation="weighted_mean",
                            scope="uk.ew", name=name, scorable=False, description=desc)
        register_metric(ctx, "uk.benefit.uc_working_share", category="people", dataset="uk.dwp.uc_people",
                        value_type="percent", unit="%", decimals=1, direction=0, period_type="month", native_level="lsoa",
                        aggregation="weighted_mean", scope="uk.ew", name="People on Universal Credit who are in work",
                        scorable=False, description="DWP Stat-Xplore People on Universal Credit by employment indicator")
        ids = [*UC_METRICS, "uk.benefit.uc_working_share"]
        ctx.sql("xoá giá trị cùng kỳ", "DELETE FROM core.metric_value WHERE metric_id = ANY(%s) AND period = %s", (ids, period))
        n = 0
        for mid, (_, expr) in UC_METRICS.items():
            n += ctx.sql(mid, f"""INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size, release_id)
                SELECT 'uk', s.area_id, %s, %s, round((100 * {expr} / s.pop1664)::numeric, 2), round(s.pop1664)::int, %s
                FROM uc_lsoa s WHERE s.pop1664 > 0""", (mid, period, ctx.release_id))
        n += ctx.sql("uc_working_share", """INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size, release_id)
            SELECT 'uk', s.area_id, 'uk.benefit.uc_working_share', %s, round((100 * s.working / s.total)::numeric, 1),
                   round(s.total)::int, %s
            FROM uc_lsoa s WHERE s.total >= 10""", (period, ctx.release_id))
        ctx.drop_stage("uc")
        return {"lsoa": n_lsoa, "values": n, "ew_rate_per_100": round(rate, 2), "blackpool": round(bp, 1), "wokingham": round(wk, 1)}


# ------------------------------------------------- HMLR: công ty sở hữu nhà -----
COMPANY_DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.company_title (
    title_number text NOT NULL,
    is_overseas boolean NOT NULL,
    tenure text,
    district text,
    postcode text,
    price_paid numeric,
    proprietor_name text NOT NULL,
    company_reg_no text,
    proprietorship_category text,
    country_incorporated text,
    proprietor_count smallint,
    date_proprietor_added date,
    release_id bigint REFERENCES ops.dataset_release (id),
    PRIMARY KEY (title_number, is_overseas)
);
CREATE INDEX IF NOT EXISTS company_title_postcode_idx ON mkt_uk.company_title (postcode);
COMMENT ON TABLE mkt_uk.company_title IS 'HM Land Registry CCOD (công ty UK) + OCOD (công ty nước ngoài): sổ đỏ (title) England & Wales do pháp nhân sở hữu. Chỉ giữ chủ sở hữu thứ nhất; proprietor_count = số chủ. KHÔNG lưu địa chỉ bất động sản: licence (điều 3.2) chỉ cho dùng địa chỉ AddressBase/PAF phi thương mại → chỉ giữ postcode để thống kê theo khu.';
ALTER TABLE mkt_uk.company_title DROP COLUMN IF EXISTS property_address"""

CCOD_COLS = ["Title Number", "Tenure", "Property Address", "District", "County", "Region", "Postcode",
             "Multiple Address Indicator", "Price Paid", "Proprietor Name (1)", "Company Registration No. (1)",
             "Proprietorship Category (1)"]


def _date(v: str | None):
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(v.strip(), fmt).date()
        except (AttributeError, ValueError):
            continue
    return None


class CompanyOwnershipLoader(Loader):
    """CCOD hoặc OCOD → mkt_uk.company_title (thay phần của nguồn đó) + chỉ số theo LSOA trên tổng hai bảng."""

    def __init__(self, source: str, overseas: bool, min_rows: int, max_rows: int):
        self.source = source
        self.overseas = overseas
        self.min_rows, self.max_rows = min_rows, max_rows
        self.depends_on = ("onspd", "census2021")
        self.description = (f"HMLR {'OCOD' if overseas else 'CCOD'} → mkt_uk.company_title + "
                            f"uk.own.{'overseas' if overseas else 'company'}_titles_per_1k_hh (LSOA)")

    def rows(self, ctx: LoadContext):
        z = ctx.file(r"_FULL_\d{4}_\d{2}\.zip$")
        members = zip_members(z, r"\.csv$")
        if len(members) != 1:
            raise LoadError(f"{z.name}: cần đúng 1 CSV, thấy {members}")
        with zipfile.ZipFile(z) as zf, zf.open(members[0]) as f:
            r = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))
            miss = [c for c in CCOD_COLS if c not in (r.fieldnames or [])]
            if miss:
                raise LoadError(f"{members[0]} thiếu cột {miss} (có {r.fieldnames[:20]})")
            n_prop_cols = sum(1 for c in r.fieldnames if re.fullmatch(r"Proprietor Name \(\d\)", c))
            for row in r:
                title = (row["Title Number"] or "").strip()
                name = (row["Proprietor Name (1)"] or "").strip()
                if not title or not name:
                    continue
                pc = re.sub(r"\s+", " ", (row["Postcode"] or "").strip().upper()) or None
                try:
                    price = float(row["Price Paid"]) if row["Price Paid"] else None
                except ValueError:
                    price = None
                n_owners = sum(1 for i in range(1, n_prop_cols + 1) if (row.get(f"Proprietor Name ({i})") or "").strip())
                yield (title, self.overseas, row["Tenure"] or None, row["District"] or None,
                       pc, price, name, row["Company Registration No. (1)"] or None,
                       row["Proprietorship Category (1)"] or None, row.get("Country Incorporated (1)") or None,
                       n_owners, _date(row.get("Date Proprietor Added")), ctx.release_id)

    def load(self, ctx: LoadContext) -> dict:
        _ddl(ctx, COMPANY_DDL)
        cols = ["title_number", "is_overseas", "tenure", "district", "postcode", "price_paid",
                "proprietor_name", "company_reg_no", "proprietorship_category", "country_incorporated",
                "proprietor_count", "date_proprietor_added", "release_id"]
        st = ctx.stage_table("company_title", cols, {"is_overseas": "boolean", "price_paid": "numeric",
                                                     "proprietor_count": "smallint", "date_proprietor_added": "date",
                                                     "release_id": "bigint"})
        n = ctx.copy_rows(st, cols, self.rows(ctx), f"COPY {self.source}")
        if not self.min_rows <= n <= self.max_rows:
            raise LoadError(f"Số title {self.source} bất thường: {n:,} (kỳ vọng {self.min_rows:,}–{self.max_rows:,})")
        ctx.check_values_in("tenure", st, "tenure", ["Freehold", "Leasehold"])
        if self.overseas:
            ctx.check_not_null_ratio("nước đăng ký", st, "nullif(country_incorporated, '')", 0.95)
        ctx.check_not_null_ratio("postcode", st, "postcode", 0.6)
        ctx.sql(f"xoá bản cũ ({self.source})", "DELETE FROM mkt_uk.company_title WHERE is_overseas = %s", (self.overseas,))
        ins = ctx.sql("INSERT company_title", f"""
            INSERT INTO mkt_uk.company_title ({", ".join(cols)})
            SELECT DISTINCT ON (title_number) {", ".join(cols)} FROM {st} ORDER BY title_number, date_proprietor_added DESC NULLS LAST""")
        pc_match = ctx.scalar(f"""SELECT avg((p.postcode IS NOT NULL)::int) FROM {st} s
            LEFT JOIN mkt_uk.postcode p ON p.postcode = s.postcode WHERE s.postcode IS NOT NULL""")
        log.info("    %s title, %.1f%% postcode khớp ONSPD", f"{ins:,}", pc_match * 100)
        if pc_match < 0.9:
            raise LoadError(f"Chỉ {pc_match:.1%} postcode khớp ONSPD")
        ctx.drop_stage("company_title")
        return {"titles": ins, "postcode_match": round(pc_match, 4), **self.metrics(ctx)}

    def metrics(self, ctx: LoadContext) -> dict:
        """Số title công ty (UK hoặc nước ngoài) / 1.000 hộ (Census 2021 ts041) theo LSOA."""
        mid = f"uk.own.{'overseas' if self.overseas else 'company'}_titles_per_1k_hh"
        y, m = map(int, ctx.version.split("-"))
        period = date(y, m, 1)
        who = "overseas companies" if self.overseas else "UK companies"
        register_metric(ctx, mid, category="housing", dataset=f"uk.land_registry.{'ocod' if self.overseas else 'ccod'}",
                        value_type="number", unit="per 1,000 households", decimals=1, direction=0, period_type="month",
                        native_level="lsoa", aggregation="weighted_mean", scope="uk.ew", scorable=False,
                        name=f"Land titles owned by {who} per 1,000 households",
                        description=f"HM Land Registry {'OCOD' if self.overseas else 'CCOD'} titles (residential and "
                                    "commercial) by property postcode ÷ Census 2021 households")
        ctx.sql("xoá giá trị cũ", "DELETE FROM core.metric_value WHERE metric_id = %s", (mid,))
        n = ctx.sql(mid, """
            INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size, release_id)
            SELECT 'uk', a.id, %s, %s, round((1000.0 * coalesce(t.n, 0) / hh.value_num)::numeric, 1),
                   coalesce(t.n, 0), %s
            FROM core.geo_area a
            JOIN core.metric_value hh ON hh.market_code = 'uk' AND hh.area_id = a.id AND hh.metric_id = 'uk.census21.ts041' AND hh.value_num > 0
            LEFT JOIN (SELECT p.lsoa21_code, count(*) n FROM mkt_uk.company_title c
                       JOIN mkt_uk.postcode p ON p.postcode = c.postcode WHERE c.is_overseas = %s GROUP BY 1) t
                   ON t.lsoa21_code = a.code
            WHERE a.market_code = 'uk' AND a.level_code = 'lsoa'""", (mid, period, ctx.release_id, self.overseas))
        # định hướng: Westminster (nhiều công ty sở hữu) cao hơn Cornwall
        wm, co = (ctx.scalar("""SELECT sum(v.value_num * v2.value_num) / sum(v2.value_num) FROM core.metric_value v
                    JOIN core.geo_area a ON a.id = v.area_id
                    JOIN core.metric_value v2 ON v2.market_code = 'uk' AND v2.area_id = a.id AND v2.metric_id = 'uk.census21.ts041'
                    WHERE v.market_code = 'uk' AND v.metric_id = %s AND a.code IN (SELECT DISTINCT lsoa21_code FROM mkt_uk.postcode WHERE lad_code = %s)""",
                              (mid, c)) for c in ("E09000033", "E06000052"))
        log.info("    %s: Westminster %.1f, Cornwall %.1f / 1.000 hộ", mid, wm or 0, co or 0)
        if not (wm and co is not None and wm > co):
            raise LoadError(f"Kiểm tra định hướng {mid} thất bại: Westminster {wm}, Cornwall {co}")
        return {"metric_values": n, "westminster": round(wm, 1), "cornwall": round(co or 0, 1)}


# --------------------------------------------------- HMLR Registered Leases -----
LEASES_DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.registered_lease (
    unique_id text PRIMARY KEY,
    tenure text,
    register_property_description text,
    county text,
    region text,
    associated_property_description text,
    uprn bigint,
    price_paid numeric,
    date_of_lease date,
    term text,
    term_years int,
    term_start date,
    term_end date,
    alienation_clause boolean,
    release_id bigint REFERENCES ops.dataset_release (id)
);
CREATE INDEX IF NOT EXISTS registered_lease_uprn_idx ON mkt_uk.registered_lease (uprn);
COMMENT ON TABLE mkt_uk.registered_lease IS 'HM Land Registry Registered Leases: hợp đồng thuê dài hạn đã đăng ký (England & Wales). term_years/term_start/term_end tách từ chuỗi Term ("99 years from 25 March 1985"); NULL khi không đọc được.'"""
LEASE_COLS = ["Unique Identifier", "Tenure", "Register Property Description", "County", "Region",
              "Associated Property Description", "OS UPRN", "Price Paid", "Date of Lease", "Term", "Alienation Clause Indicator"]
TERM_RE = re.compile(r"(\d{1,4})\s+years?\b.*?\b(?:from|commencing(?: on)?|beginning(?: on)?|starting(?: on)?)\s+"
                     r"(?:and including\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s+(\d{4})", re.I)
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def parse_term(term: str | None):
    m = TERM_RE.search(term or "")
    if not m:
        return None, None, None
    years, day, mon, year = int(m.group(1)), int(m.group(2)), MONTHS.get(m.group(3).lower()), int(m.group(4))
    if not mon or not 1 <= years <= 3000 or not 1500 <= year <= 2100:
        return None, None, None
    try:
        start = date(year, mon, day)
        end = date(min(year + years, 9999), mon, 28 if (mon == 2 and day == 29) else day)
    except ValueError:
        return None, None, None
    return years, start, end


class RegisteredLeasesLoader(Loader):
    source = "hmlr_leases"
    description = "HMLR Registered Leases → mkt_uk.registered_lease (thời hạn thuê, ngày bắt đầu/kết thúc theo UPRN)"

    def load(self, ctx: LoadContext) -> dict:
        _ddl(ctx, LEASES_DDL)
        z = ctx.file(r"_FULL_\d{4}_\d{2}\.zip$")
        members = zip_members(z, r"\.csv$")
        if len(members) != 1:
            raise LoadError(f"{z.name}: cần đúng 1 CSV, thấy {members}")
        stats = {"rows": 0, "parsed": 0}

        def rows():
            with zipfile.ZipFile(z) as zf, zf.open(members[0]) as f:
                r = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))
                miss = [c for c in LEASE_COLS if c not in (r.fieldnames or [])]
                if miss:
                    raise LoadError(f"Leases thiếu cột {miss} (có {r.fieldnames})")
                for row in r:
                    uid = (row["Unique Identifier"] or "").strip()
                    if not uid:
                        continue
                    stats["rows"] += 1
                    years, start, end = parse_term(row["Term"])
                    stats["parsed"] += years is not None
                    uprn = row["OS UPRN"].strip() if row["OS UPRN"] else ""
                    try:
                        price = float(row["Price Paid"]) if row["Price Paid"] else None
                    except ValueError:
                        price = None
                    yield (uid, row["Tenure"] or None, row["Register Property Description"] or None, row["County"] or None,
                           row["Region"] or None, row["Associated Property Description"] or None,
                           int(uprn) if uprn.isdigit() else None, price, _date(row["Date of Lease"]), row["Term"] or None,
                           years, start, end, {"Y": True, "N": False}.get((row["Alienation Clause Indicator"] or "").strip()),
                           ctx.release_id)
        cols = ["unique_id", "tenure", "register_property_description", "county", "region", "associated_property_description",
                "uprn", "price_paid", "date_of_lease", "term", "term_years", "term_start", "term_end", "alienation_clause",
                "release_id"]
        ctx.sql("TRUNCATE registered_lease", "TRUNCATE mkt_uk.registered_lease")
        n = ctx.copy_rows("mkt_uk.registered_lease", cols, rows(), "COPY leases")
        if not 5_000_000 <= n <= 10_000_000:
            raise LoadError(f"Số hợp đồng thuê bất thường: {n:,} (~7,8 triệu)")
        parsed = stats["parsed"] / max(stats["rows"], 1)
        log.info("    tách được thời hạn: %.1f%%", parsed * 100)
        if parsed < 0.6:
            raise LoadError(f"Chỉ tách được thời hạn của {parsed:.1%} hợp đồng — định dạng Term đổi?")
        ctx.check_range("số năm thuê", "mkt_uk.registered_lease", "term_years", 1, 3000)
        return {"leases": n, "term_parsed": round(parsed, 3)}


EXTRA2_LOADERS = [
    GpPatientSurveyLoader(), UniversalCreditLoader(),
    CompanyOwnershipLoader("hmlr_ccod", False, 3_500_000, 5_500_000),
    CompanyOwnershipLoader("hmlr_ocod", True, 60_000, 130_000),
    RegisteredLeasesLoader(),
]
