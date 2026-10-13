"""Nạp POI: GIAS (trường) + Ofsted (đánh giá), NaPTAN (giao thông), NHS ODS (y tế), FSA (ăn uống + điểm vệ sinh)."""
from __future__ import annotations

import csv
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

from .base import LoadContext, LoadError, Loader, slug_sql

log = logging.getLogger(__name__)


def close_missing(ctx: LoadContext, scheme: str, types: list[str]) -> int:
    """POI cùng scheme/loại không được upsert ở release này (release_id khác) → status closed.

    Upsert luôn gán release_id hiện tại cho mọi POI còn trong nguồn, nên so release_id là đủ và chạy O(n)
    (bản trước dùng NOT EXISTS lồng trên bảng stage → O(n²), treo hàng chục phút).
    """
    return ctx.sql("đóng POI không còn trong nguồn", """
        UPDATE core.poi p SET status = 'closed', closed_on = coalesce(closed_on, current_date)
        WHERE p.market_code = 'uk' AND p.external_scheme = %s AND p.type_code = ANY(%s) AND p.status <> 'closed'
          AND p.release_id IS DISTINCT FROM %s""", (scheme, types, ctx.release_id))


NEAREST_POSTCODE_SQL = """
    -- POI không có postcode (NaPTAN) hoặc postcode không khớp ONSPD → gắn area_id = postcode đang dùng gần nhất (≤ 1 km)
    UPDATE core.poi p SET area_id = n.area_id
    FROM (SELECT p2.id, pc.area_id
          FROM core.poi p2
          CROSS JOIN LATERAL (SELECT pc.area_id, pc.geom FROM mkt_uk.postcode pc
                              WHERE pc.status = 'live' AND pc.geom IS NOT NULL
                              ORDER BY pc.geom <-> p2.geom LIMIT 1) pc
          WHERE p2.market_code = 'uk' AND p2.area_id IS NULL AND p2.external_scheme = %s
            AND ST_DWithin(pc.geom::geography, p2.geom::geography, 1000)) n
    WHERE p.id = n.id"""


def attach_nearest_postcode(ctx: LoadContext, scheme: str) -> int:
    return ctx.sql("gắn area_id = postcode gần nhất (POI thiếu)", NEAREST_POSTCODE_SQL, (scheme,))


POI_UPSERT_SET = """name = EXCLUDED.name, slug = EXCLUDED.slug, type_code = EXCLUDED.type_code, geom = EXCLUDED.geom,
    address = EXCLUDED.address, postal_code = EXCLUDED.postal_code, area_id = EXCLUDED.area_id,
    status = EXCLUDED.status, opened_on = EXCLUDED.opened_on, closed_on = EXCLUDED.closed_on,
    attrs = EXCLUDED.attrs, release_id = EXCLUDED.release_id"""


# ======================================================================= GIAS =====
# Trường Wales được loader wales_schools làm giàu (cấp học, ngôn ngữ...) → nạp lại GIAS không được ghi đè phần đó
GIAS_UPSERT_SET = POI_UPSERT_SET.replace(
    "type_code = EXCLUDED.type_code",
    "type_code = CASE WHEN core.poi.attrs ? 'wales_sector' THEN core.poi.type_code ELSE EXCLUDED.type_code END",
).replace("attrs = EXCLUDED.attrs", "attrs = core.poi.attrs || EXCLUDED.attrs")
assert GIAS_UPSERT_SET != POI_UPSERT_SET
class GiasLoader(Loader):
    source = "gias"
    depends_on = ("onspd",)
    description = "GIAS → core.poi (school.*, college); toạ độ từ Easting/Northing, thiếu thì lấy theo postcode"

    def load(self, ctx: LoadContext) -> dict:
        f = ctx.file(r"^edubasealldata\d+\.csv$")
        with open(f, encoding="cp1252", newline="") as fh:
            header = next(csv.reader(fh))
        t = ctx.stage_table("gias", header)
        with open(f, "rb") as fh:
            n = ctx.copy_csv(t, fh, encoding="WIN1252", label=f"COPY {f.name}")
        c = lambda name: f'g."{name}"'  # noqa: E731
        ptype = f"""CASE
            WHEN {c('EstablishmentTypeGroup (name)')} IN ('Colleges', 'Universities') THEN 'college'
            WHEN {c('EstablishmentTypeGroup (name)')} = 'Special schools' THEN 'school.special'
            WHEN {c('PhaseOfEducation (name)')} = 'Nursery' THEN 'school.nursery'
            WHEN {c('PhaseOfEducation (name)')} IN ('Primary', 'Middle deemed primary') THEN 'school.primary'
            WHEN {c('PhaseOfEducation (name)')} IN ('Secondary', 'Middle deemed secondary') THEN 'school.secondary'
            WHEN {c('PhaseOfEducation (name)')} = 'All-through' THEN 'school.all_through'
            WHEN {c('PhaseOfEducation (name)')} = '16 plus' THEN 'school.post16'
            ELSE 'school.other' END"""
        status = f"""CASE {c('EstablishmentStatus (name)')} WHEN 'Closed' THEN 'closed' WHEN 'Proposed to open' THEN 'proposed'
                     ELSE 'open' END"""
        attrs_keys = ["URN", "UKPRN", "LA (code)", "EstablishmentNumber", "LA (name)", "TypeOfEstablishment (name)", "EstablishmentTypeGroup (name)",
                      "PhaseOfEducation (name)", "StatutoryLowAge", "StatutoryHighAge", "Gender (name)",
                      "ReligiousCharacter (name)", "AdmissionsPolicy (name)", "OfficialSixthForm (name)",
                      "NurseryProvision (name)", "SchoolCapacity", "NumberOfPupils", "PercentageFSM", "Trusts (name)",
                      "SchoolWebsite", "TelephoneNum", "UPRN", "EstablishmentStatus (name)"]
        attrs = "jsonb_strip_nulls(jsonb_build_object(" + ", ".join(
            f"'{k}', nullif({c(k)}, '')" for k in attrs_keys) + "))"
        geom = f"""coalesce(
            CASE WHEN {c('Easting')} ~ '^[0-9]+$' AND {c('Easting')}::int > 0
                 THEN ST_Transform(ST_SetSRID(ST_MakePoint({c('Easting')}::float8, {c('Northing')}::float8), 27700), 4326) END,
            pc.geom)"""
        address = f"concat_ws(', ', nullif({c('Street')}, ''), nullif({c('Locality')}, ''), nullif({c('Address3')}, ''), nullif({c('Town')}, ''))"
        ctx.sql("upsert core.poi (trường)", f"""
            INSERT INTO core.poi (market_code, type_code, external_scheme, external_id, name, slug, geom, address,
                postal_code, area_id, status, opened_on, closed_on, attrs, dataset_id, release_id)
            SELECT 'uk', {ptype}, 'urn', g."URN", g."EstablishmentName",
                   g."URN" || '-' || {slug_sql('g."EstablishmentName"')}, {geom}, {address},
                   nullif(g."Postcode", ''), pc.area_id, {status},
                   to_date(nullif(g."OpenDate", ''), 'DD-MM-YYYY'), to_date(nullif(g."CloseDate", ''), 'DD-MM-YYYY'),
                   {attrs}, 'uk.dfe.gias', %s
            FROM {t} g LEFT JOIN mkt_uk.postcode pc ON pc.postcode = nullif(g."Postcode", '')
            WHERE {geom} IS NOT NULL
            ON CONFLICT (market_code, external_scheme, external_id) DO UPDATE SET {GIAS_UPSERT_SET}""",
                (ctx.release_id,))
        no_geom = ctx.scalar(f"""SELECT count(*) FROM {t} g LEFT JOIN mkt_uk.postcode pc ON pc.postcode = nullif(g."Postcode", '')
                                 WHERE {geom} IS NULL""")
        open_no_geom = ctx.scalar(f"""SELECT count(*) FROM {t} g LEFT JOIN mkt_uk.postcode pc ON pc.postcode = nullif(g."Postcode", '')
                                      WHERE {geom} IS NULL AND g."EstablishmentStatus (name)" <> 'Closed'""")
        log.info("    bỏ qua %s cơ sở không có toạ độ/postcode (trong đó %s đang mở)", no_geom, open_no_geom)
        n_db = ctx.scalar("SELECT count(*) FROM core.poi WHERE market_code='uk' AND external_scheme='urn' AND release_id=%s",
                          (ctx.release_id,))
        ctx.expect("core.poi trường (+ bỏ qua không toạ độ)", n_db + no_geom, n)
        ctx.drop_stage("gias")
        return {"rows": n, "no_geom": no_geom}


# ===================================================================== Ofsted =====
REPORT_CARD = [  # (cột điểm, cột ngày, aspect)
    ("Safeguarding standards", "Safeguarding standards - date of grade", "safeguarding"),
    ("Inclusion", "Inclusion - date of grade", "inclusion"),
    ("Curriculum and teaching", "Curriculum and teaching - date of grade", "curriculum_teaching"),
    ("Achievement", "Achievement - date of grade", "achievement"),
    ("Attendance and behaviour", "Attendance and behaviour - date of grade", "attendance_behaviour"),
    ("Personal development and wellbeing", "Personal development and wellbeing - date of grade", "personal_development"),
    ("Early years (where applicable)", "Early years - date of grade", "early_years"),
    ("Post-16 provision (where applicable)", "Post-16 provision - date of grade", "post16"),
    ("Leadership and governance", "Leadership and governance - date of grade", "leadership"),
]
REPORT_CARD_RANK = {"Exceptional": 1, "Strong standard": 2, "Expected standard": 3, "Needs attention": 4,
                    "Urgent improvement": 5, "Met": 1, "Not met": 2}
OEIF = [
    ("Latest OEIF overall effectiveness", "overall"),
    ("Latest OEIF quality of education", "quality_of_education"),
    ("Latest OEIF behaviour and attitudes", "behaviour_attitudes"),
    ("Latest OEIF personal development", "personal_development"),
    ("Latest OEIF effectiveness of leadership and management", "leadership"),
    ("Latest OEIF  safeguarding is effective?", "safeguarding"),
    ("Latest OEIF early years provision (where applicable)", "early_years"),
    ("Latest OEIF sixth form provision (where applicable)", "sixth_form"),
]
OEIF_LABEL = {"1": "Outstanding", "2": "Good", "3": "Requires improvement", "4": "Inadequate",
              "Yes": "Effective", "No": "Not effective"}


def _d(s: str):
    s = (s or "").strip()
    if not s or s.upper() == "NULL":
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise LoadError(f"Ngày không đọc được: {s!r}")


def _v(s: str):
    s = (s or "").strip()
    return None if not s or s.upper() in ("NULL", "NOT JUDGED", "N/A", "NOT APPLICABLE") else s


class OfstedLoader(Loader):
    source = "ofsted"
    depends_on = ("gias",)
    description = "Ofsted MI → core.poi_rating: report card (scheme ofsted_report_card) + OEIF cũ (scheme ofsted_oeif)"

    def load(self, ctx: LoadContext) -> dict:
        f = ctx.file(r"latest_inspections.*\.csv$")
        rows = []
        with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
            rd = csv.DictReader(fh)
            missing = [c for c, *_ in REPORT_CARD + OEIF if c not in rd.fieldnames]
            if missing:
                raise LoadError(f"File Ofsted thiếu cột (định dạng đổi?): {missing}")
            n_src, odd = 0, {}
            for r in rd:
                n_src += 1
                urn = r["URN"].strip()
                pub = _d(r.get("Publication date"))
                for col, dcol, aspect in REPORT_CARD:
                    g = _v(r[col])
                    if g:
                        rated = _d(r[dcol]) or _d(r["Inspection start date"])
                        if g not in REPORT_CARD_RANK:
                            odd[(col, g)] = odd.get((col, g), 0) + 1
                            continue
                        rows.append((urn, "ofsted_report_card", aspect, g, g, REPORT_CARD_RANK.get(g),
                                     2 if aspect == "safeguarding" else 5, rated, pub))
                rated = _d(r["Inspection start date of latest OEIF graded inspection"])
                opub = _d(r["Publication date of latest OEIF graded inspection"])
                for col, aspect in OEIF:
                    g = _v(r[col])
                    if g and g not in OEIF_LABEL:  # 9 = không áp dụng, 0 = không chấm
                        odd[(col, g)] = odd.get((col, g), 0) + 1
                        continue
                    if g and rated:
                        rank = int(g) if g.isdigit() else (1 if g == "Yes" else 2)
                        rows.append((urn, "ofsted_oeif", aspect, g, OEIF_LABEL.get(g, g), rank,
                                     2 if aspect == "safeguarding" else 4, rated, opub))
        if odd:  # gom một dòng thay vì cảnh báo từng trường
            log.warning("    bỏ qua giá trị report card không nằm trong thang điểm: %s", odd)
        cols = ["urn", "scheme", "aspect", "grade_code", "grade_label", "grade_rank", "scale_max", "rated_on", "published_on"]
        t = ctx.stage_table("ofsted", cols, {"grade_rank": "smallint", "scale_max": "smallint",
                                             "rated_on": "date", "published_on": "date"})
        ctx.copy_rows(t, cols, rows, "COPY rating rows")
        unmatched = ctx.scalar(f"""SELECT count(DISTINCT urn) FROM {t} s WHERE NOT EXISTS
            (SELECT 1 FROM core.poi p WHERE p.market_code='uk' AND p.external_scheme='urn' AND p.external_id = s.urn)""")
        if unmatched:
            log.warning("    %s URN có đánh giá nhưng không có trong GIAS → bỏ qua", unmatched)
        ctx.sql("upsert core.poi_rating", f"""
            INSERT INTO core.poi_rating (poi_id, scheme, aspect, grade_code, grade_label, grade_rank, grade_scale_max,
                                         rated_on, published_on, is_current, release_id)
            SELECT p.id, s.scheme, s.aspect, s.grade_code, s.grade_label, s.grade_rank, s.scale_max, s.rated_on,
                   s.published_on, true, %s
            FROM {t} s JOIN core.poi p ON p.market_code='uk' AND p.external_scheme='urn' AND p.external_id = s.urn
            ON CONFLICT (poi_id, scheme, aspect, rated_on) DO UPDATE SET grade_code = EXCLUDED.grade_code,
                grade_label = EXCLUDED.grade_label, grade_rank = EXCLUDED.grade_rank,
                published_on = EXCLUDED.published_on, release_id = EXCLUDED.release_id""", (ctx.release_id,))
        ctx.sql("is_current = chỉ bản mới nhất mỗi (poi, scheme, aspect)", """
            UPDATE core.poi_rating r SET is_current = (r.rated_on = m.max_on)
            FROM (SELECT poi_id, scheme, aspect, max(rated_on) max_on FROM core.poi_rating
                  WHERE scheme LIKE 'ofsted%%' GROUP BY 1, 2, 3) m
            WHERE r.poi_id = m.poi_id AND r.scheme = m.scheme AND r.aspect = m.aspect
              AND r.is_current IS DISTINCT FROM (r.rated_on = m.max_on)""")
        n_db = ctx.scalar("SELECT count(*) FROM core.poi_rating WHERE release_id = %s", (ctx.release_id,))
        expected = ctx.scalar(f"""SELECT count(*) FROM {t} s JOIN core.poi p ON p.market_code='uk'
                                  AND p.external_scheme='urn' AND p.external_id = s.urn""")
        ctx.expect("core.poi_rating Ofsted", n_db, expected)
        ctx.drop_stage("ofsted")
        return {"schools_in_file": n_src, "ratings": n_db, "unmatched_urn": unmatched}


# ===================================================================== NaPTAN =====
NAPTAN_TYPES = {"BCT": "stop.bus", "BCS": "stop.bus", "BCQ": "stop.bus", "BST": "station.bus",
                "RLY": "station.rail", "MET": "station.metro", "FER": "station.ferry", "AIR": "airport"}


class NaptanLoader(Loader):
    source = "naptan"
    depends_on = ("onspd",)
    description = "NaPTAN → core.poi (stop.bus, station.rail, station.metro, ...), chỉ điểm dừng active"

    def load(self, ctx: LoadContext) -> dict:
        f = ctx.file(r"\.csv$")
        with open(f, encoding="utf-8-sig", newline="") as fh:
            header = next(csv.reader(fh))
        t = ctx.stage_table("naptan", header)
        with open(f, "rb") as fh:
            n = ctx.copy_csv(t, fh, label=f"COPY {f.name}")
        mapping = "CASE n.\"StopType\" " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in NAPTAN_TYPES.items()) + " END"
        geom = """coalesce(
            CASE WHEN n."Longitude" ~ '^-?[0-9.]+$' THEN ST_SetSRID(ST_MakePoint(n."Longitude"::float8, n."Latitude"::float8), 4326) END,
            CASE WHEN n."Easting" ~ '^[0-9]+$' THEN ST_Transform(ST_SetSRID(ST_MakePoint(n."Easting"::float8, n."Northing"::float8), 27700), 4326) END)"""
        keep = f"""lower(n."Status") = 'active' AND n."StopType" IN ({", ".join(f"'{k}'" for k in NAPTAN_TYPES)})
                   AND {geom} IS NOT NULL"""
        expected = ctx.scalar(f"SELECT count(*) FROM {t} n WHERE {keep}")
        ctx.sql("upsert core.poi (giao thông)", f"""
            INSERT INTO core.poi (market_code, type_code, external_scheme, external_id, name, slug, geom, address,
                                  status, attrs, dataset_id, release_id)
            SELECT 'uk', {mapping}, 'atco', n."ATCOCode", n."CommonName",
                   CASE WHEN n."StopType" IN ('RLY', 'MET') THEN lower(n."ATCOCode") || '-' || {slug_sql('n."CommonName"')} END,
                   {geom}, concat_ws(', ', nullif(n."Street", ''), nullif(n."LocalityName", '')), 'open',
                   jsonb_strip_nulls(jsonb_build_object('naptan_code', nullif(n."NaptanCode", ''),
                       'stop_type', n."StopType", 'indicator', nullif(n."Indicator", ''), 'bearing', nullif(n."Bearing", ''),
                       'locality', nullif(n."LocalityName", ''), 'town', nullif(n."Town", ''),
                       'admin_area', nullif(n."AdministrativeAreaCode", ''))),
                   'uk.dft.naptan', %s
            FROM {t} n WHERE {keep}
            ON CONFLICT (market_code, external_scheme, external_id) DO UPDATE SET {POI_UPSERT_SET}""",
                (ctx.release_id,))
        closed = close_missing(ctx, "atco", list(set(NAPTAN_TYPES.values())))
        attach_nearest_postcode(ctx, "atco")
        n_db = ctx.scalar("SELECT count(*) FROM core.poi WHERE external_scheme='atco' AND release_id=%s", (ctx.release_id,))
        ctx.expect("core.poi NaPTAN", n_db, expected)
        ctx.drop_stage("naptan")
        return {"rows_in_file": n, "loaded": n_db, "closed": closed}


# ==================================================================== NHS ODS =====
ODS_COLS = ["code", "name", "national_grouping", "hlhg", "addr1", "addr2", "addr3", "addr4", "addr5", "postcode",
            "open_date", "close_date", "status", "sub_type", "parent", "join_date", "left_date", "phone",
            "c18", "c19", "c20", "amended", "c22", "c23", "c24", "role", "c26"]
ODS_REPORTS = {  # file → (poi type, điều kiện lọc thêm)
    "epraccur": ("health.gp", "role = 'RO76'"),           # chỉ GP practice (bỏ OOH, walk-in, ...)
    "edispensary": ("health.pharmacy", "true"),
    "egdpprac": ("health.dentist", "true"),
    "ets": ("health.trust_site", "true"),
}


class NhsOdsLoader(Loader):
    source = "nhs_ods"
    depends_on = ("onspd",)
    description = "NHS ODS → core.poi (health.gp, pharmacy, dentist, trust_site); toạ độ theo postcode"

    def load(self, ctx: LoadContext) -> dict:
        stats = {}
        for report, (ptype, cond) in ODS_REPORTS.items():
            f = ctx.file(rf"^{report}\.csv$")
            t = ctx.stage_table(f"ods_{report}", ODS_COLS)
            with open(f, "rb") as fh:
                n = ctx.copy_csv(t, fh, header=False, encoding="LATIN1", label=f"COPY {f.name}")
            is_open = "(o.status IN ('ACTIVE', '') AND nullif(o.close_date, '') IS NULL)"
            ctx.sql(f"upsert core.poi {ptype}", f"""
                INSERT INTO core.poi (market_code, type_code, external_scheme, external_id, name, geom, address,
                    postal_code, area_id, status, opened_on, closed_on, attrs, dataset_id, release_id)
                SELECT 'uk', %(ptype)s, 'ods', o.code, initcap(o.name), pc.geom,
                       initcap(concat_ws(', ', nullif(o.addr1, ''), nullif(o.addr2, ''), nullif(o.addr3, ''), nullif(o.addr4, ''))),
                       o.postcode, pc.area_id,
                       CASE WHEN o.status = 'PROPOSED' THEN 'proposed' WHEN {is_open} THEN 'open' ELSE 'closed' END,
                       to_date(nullif(o.open_date, ''), 'YYYYMMDD'), to_date(nullif(o.close_date, ''), 'YYYYMMDD'),
                       jsonb_strip_nulls(jsonb_build_object('phone', nullif(o.phone, ''), 'parent', nullif(o.parent, ''),
                           'role', nullif(o.role, ''), 'ods_status', nullif(o.status, ''), 'report', %(report)s::text)),
                       'uk.nhs.ods', %(rel)s
                FROM {t} o JOIN mkt_uk.postcode pc ON pc.postcode = o.postcode AND pc.geom IS NOT NULL
                WHERE {cond}
                ON CONFLICT (market_code, external_scheme, external_id) DO UPDATE SET {POI_UPSERT_SET}""",
                    {"ptype": ptype, "report": report, "rel": ctx.release_id})
            eligible = ctx.scalar(f"SELECT count(*) FROM {t} o WHERE {cond}")
            no_pc = ctx.scalar(f"""SELECT count(*) FROM {t} o WHERE {cond} AND NOT EXISTS
                (SELECT 1 FROM mkt_uk.postcode pc WHERE pc.postcode = o.postcode AND pc.geom IS NOT NULL)""")
            if no_pc:
                log.info("    %s: %s bản ghi không ghép được postcode → bỏ qua", report, no_pc)
            n_db = ctx.scalar("""SELECT count(*) FROM core.poi WHERE external_scheme='ods' AND type_code=%s
                                 AND release_id=%s""", (ptype, ctx.release_id))
            ctx.expect(f"core.poi {ptype}", n_db + no_pc, eligible)
            stats[report] = {"rows": n, "loaded": n_db, "no_postcode": no_pc}
            ctx.drop_stage(f"ods_{report}")
        return stats


# ======================================================================== FSA =====
FSA_TYPES = {"1": "food.restaurant", "7844": "food.takeaway", "7843": "food.pub",
             "7840": "shop.supermarket", "4613": "shop.food_retail"}
FSA_COLS = ["fhrsid", "name", "business_type", "business_type_id", "address", "postcode", "rating_value",
            "rating_key", "rating_date", "la_code", "la_name", "scheme", "hygiene", "structural", "confidence",
            "new_rating_pending", "lon", "lat"]


def _fsa_rows(paths):
    for p in paths:
        try:
            for _, el in ET.iterparse(p, events=("end",)):
                if el.tag != "EstablishmentDetail":
                    continue
                g = lambda k: (el.findtext(k) or "").strip() or None  # noqa: E731
                addr = ", ".join(x for x in (g("AddressLine1"), g("AddressLine2"), g("AddressLine3"), g("AddressLine4")) if x)
                yield (g("FHRSID"), g("BusinessName"), g("BusinessType"), g("BusinessTypeID"), addr or None,
                       g("PostCode"), g("RatingValue"), g("RatingKey"), (g("RatingDate") or "")[:10] or None,
                       g("LocalAuthorityCode"), g("LocalAuthorityName"), g("SchemeType"), g("Scores/Hygiene"),
                       g("Scores/Structural"), g("Scores/ConfidenceInManagement"), g("NewRatingPending"),
                       g("Geocode/Longitude"), g("Geocode/Latitude"))
                el.clear()
        except ET.ParseError as e:
            raise LoadError(f"XML lỗi ở {p.name}: {e}") from e


class FsaLoader(Loader):
    source = "fsa"
    depends_on = ("onspd",)
    description = "FSA XML → core.poi (food.*, shop.supermarket) + core.poi_rating (scheme fhrs/fhis)"

    def load(self, ctx: LoadContext) -> dict:
        files = [p for p in ctx.files(r"^FHRS.*\.xml$") if "cy-GB" not in p.name]  # bản tiếng Wales trùng nội dung
        if not files:
            raise LoadError("Không có file FHRS*.xml")
        t = ctx.stage_table("fsa", FSA_COLS)
        n = ctx.copy_rows(t, FSA_COLS, _fsa_rows(files), f"COPY {len(files)} file XML")
        dup = ctx.scalar(f"SELECT count(*) - count(DISTINCT fhrsid) FROM {t}")
        if dup:
            log.info("    %s FHRSID trùng giữa các file LA → giữ bản đầu", dup)
        mapping = "CASE f.business_type_id " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in FSA_TYPES.items()) + \
                  " ELSE 'food.other' END"
        geom = """coalesce(CASE WHEN f.lon ~ '^-?[0-9.]+$' AND f.lat ~ '^-?[0-9.]+$'
                               THEN ST_SetSRID(ST_MakePoint(f.lon::float8, f.lat::float8), 4326) END, pc.geom)"""
        ctx.sql("upsert core.poi (FSA)", f"""
            INSERT INTO core.poi (market_code, type_code, external_scheme, external_id, name, geom, address,
                postal_code, area_id, status, attrs, dataset_id, release_id)
            SELECT DISTINCT ON (f.fhrsid) 'uk', {mapping}, 'fhrs', f.fhrsid, f.name, {geom}, f.address, f.postcode,
                   pc.area_id, 'open',
                   jsonb_strip_nulls(jsonb_build_object('business_type', f.business_type, 'la', f.la_name,
                       'scheme', f.scheme, 'new_rating_pending', f.new_rating_pending)),
                   'uk.fsa.food_hygiene', %s
            FROM {t} f LEFT JOIN mkt_uk.postcode pc ON pc.postcode = f.postcode
            WHERE f.fhrsid IS NOT NULL AND f.name IS NOT NULL AND {geom} IS NOT NULL
            ORDER BY f.fhrsid
            ON CONFLICT (market_code, external_scheme, external_id) DO UPDATE SET {POI_UPSERT_SET}""",
                (ctx.release_id,))
        closed = close_missing(ctx, "fhrs", list(set(FSA_TYPES.values())) + ["food.other"])
        attach_nearest_postcode(ctx, "fhrs")
        ctx.sql("upsert core.poi_rating (FSA)", f"""
            INSERT INTO core.poi_rating (poi_id, scheme, aspect, grade_code, grade_label, grade_rank, grade_scale_max,
                                         rated_on, is_current, release_id)
            SELECT DISTINCT ON (p.id) p.id, lower(f.scheme), 'overall', f.rating_value, f.rating_value,
                   CASE WHEN f.rating_value ~ '^[0-5]$' THEN f.rating_value::smallint
                        WHEN f.rating_value = 'Improvement Required' THEN 0 WHEN f.rating_value = 'Pass' THEN 1
                        WHEN f.rating_value = 'Pass and Eat Safe' THEN 2 END,
                   CASE WHEN f.scheme = 'FHRS' THEN 5 ELSE 2 END, f.rating_date::date, true, %s
            FROM {t} f JOIN core.poi p ON p.market_code='uk' AND p.external_scheme='fhrs' AND p.external_id = f.fhrsid
            WHERE f.rating_date IS NOT NULL AND f.rating_value IS NOT NULL
              -- chỉ kết quả chấm thật; "Awaiting Inspection", "Exempt"... không phải điểm
              AND (f.rating_value ~ '^[0-5]$' OR f.rating_value IN ('Pass', 'Improvement Required', 'Pass and Eat Safe'))
            ORDER BY p.id
            ON CONFLICT (poi_id, scheme, aspect, rated_on) DO UPDATE SET grade_code = EXCLUDED.grade_code,
                grade_label = EXCLUDED.grade_label, grade_rank = EXCLUDED.grade_rank, release_id = EXCLUDED.release_id""",
                (ctx.release_id,))
        ctx.sql("is_current FSA", """
            UPDATE core.poi_rating r SET is_current = (r.rated_on = m.max_on)
            FROM (SELECT poi_id, scheme, max(rated_on) max_on FROM core.poi_rating
                  WHERE scheme IN ('fhrs', 'fhis') GROUP BY 1, 2) m
            WHERE r.poi_id = m.poi_id AND r.scheme = m.scheme AND r.is_current IS DISTINCT FROM (r.rated_on = m.max_on)""")
        n_poi = ctx.scalar("SELECT count(*) FROM core.poi WHERE external_scheme='fhrs' AND release_id=%s", (ctx.release_id,))
        no_geom = ctx.scalar(f"""SELECT count(DISTINCT f.fhrsid) FROM {t} f LEFT JOIN mkt_uk.postcode pc ON pc.postcode = f.postcode
                                 WHERE {geom} IS NULL""")
        log.info("    %s cơ sở không có toạ độ/postcode → bỏ qua", f"{no_geom:,}")
        ctx.expect("core.poi FSA (+ không toạ độ)", n_poi + no_geom, n - dup, tolerance=0.001)
        ctx.drop_stage("fsa")
        return {"rows": n, "poi": n_poi, "no_geom": no_geom, "closed": closed}
