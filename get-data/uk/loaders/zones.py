"""Nạp vùng polygon vào core.zone (quy hoạch, thiên nhiên, lũ) + listed building vào core.poi.

Mỗi loại vùng được thay toàn bộ trong một transaction. Kiểm tra: số polygon, toạ độ trong UK, tổng diện tích
so với số liệu công bố (khoảng rộng, vì polygon có thể chồng nhau).
"""
from __future__ import annotations

import logging
import re

from .base import STAGE, LoadContext, LoadError, Loader, zip_members

log = logging.getLogger(__name__)

UK_BBOX = "ST_MakeEnvelope(-9, 49.5, 2.5, 61.5, 4326)"


class ZoneSpec:
    def __init__(self, file, zone_type, name_fields=("name",), ext_fields=("reference", "entity", "OBJECTID"),
                 where="true", area_km2=None, min_count=1, member=None, level_rank=None, level_code=None,
                 max_count=None, nlt=None, layer=None, max_outside=None):
        self.file = file
        self.zone_type = zone_type
        self.name_fields = name_fields
        self.ext_fields = ext_fields
        self.where = where
        self.area_km2 = area_km2    # (min, max) tổng diện tích hợp lý
        self.min_count = min_count
        self.max_count = max_count
        self.member = member        # regex file bên trong zip (đọc qua /vsizip/, không giải nén)
        self.level_rank = level_rank  # biểu thức SQL trên s.* → core.zone.level_rank (mức rủi ro)
        self.level_code = level_code  # biểu thức SQL → core.zone.level_code
        self.nlt = nlt              # ép kiểu hình học cho ogr2ogr (ví dụ MULTIPOLYGON khi có Z)
        self.layer = layer          # tên layer khi file có nhiều layer (GeoPackage)
        self.max_outside = max_outside  # vùng biển (SAC/SPA) có thể vượt khung UK: số polygon được loại


def _col(cols: list[str], candidates) -> str | None:
    low = {c.lower(): c for c in cols}
    for c in candidates:
        if c.lower() in low:
            return low[c.lower()]
    return None


def load_zone(ctx: LoadContext, spec: ZoneSpec) -> dict:
    t = "z_" + spec.zone_type.replace(".", "_").replace("-", "_")
    path = ctx.file(rf"^{spec.file}$")
    src = str(path)
    if spec.member:
        members = zip_members(path, spec.member)
        if len(members) != 1:
            raise LoadError(f"{path.name}: cần đúng 1 file khớp {spec.member!r}, thấy {members}")
        src = f"/vsizip/{path}/{members[0]}"
    ctx.ogr_load(src, t, extra=["-dim", "XY"] + (["-nlt", spec.nlt] if spec.nlt else []), layer=spec.layer)
    cols = [r[0] for r in ctx.conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s", (STAGE, t))]
    name_col = _col(cols, spec.name_fields)
    ext_col = _col(cols, spec.ext_fields)
    if spec.where == "ACTIVE":  # bản ghi còn hiệu lực (ogr2ogr đổi 'end-date' → end_date, có thể thành kiểu date)
        spec_where = "(s.end_date IS NULL OR s.end_date::text = '')" if "end_date" in cols else "true"
    else:
        spec_where = spec.where
    n_src = ctx.scalar(f"SELECT count(*) FROM {STAGE}.{t} s WHERE {spec_where}")
    if n_src < spec.min_count or (spec.max_count and n_src > spec.max_count):
        raise LoadError(f"{spec.file}: {n_src} feature, ngoài khoảng hợp lý [{spec.min_count}, {spec.max_count or '∞'}]")
    # ST_CoveredBy (không phải ST_Intersects): polygon hỏng trùm cả địa cầu vẫn "giao" với khung UK.
    # So khung bao (ST_Envelope): polygon tự cắt làm GEOS ném TopologyException, còn khung bao thì luôn hợp lệ
    outside = ctx.scalar(f"SELECT count(*) FROM {STAGE}.{t} WHERE geom IS NOT NULL AND NOT ST_CoveredBy(ST_Envelope(geom), {UK_BBOX})")
    if outside > (spec.max_outside if spec.max_outside is not None else max(1, n_src * 0.0001)):
        raise LoadError(f"{spec.file}: {outside} polygon vượt khung UK (> 0,01%) — sai hệ toạ độ?")
    if outside:
        log.warning("    %s: loại %s polygon vượt khung UK (geometry hỏng)", spec.file, outside)
    spec_where = f"({spec_where}) AND ST_CoveredBy(ST_Envelope(s.geom), {UK_BBOX})"
    ctx.sql(f"xoá {spec.zone_type} cũ", "DELETE FROM core.zone WHERE market_code='uk' AND type_code=%s", (spec.zone_type,))
    other = [c for c in cols if c not in ("geom", "ogc_fid") and c != name_col]
    attrs = "jsonb_strip_nulls(jsonb_build_object(" + ", ".join(f"'{c}', s.\"{c}\"" for c in other[:40]) + "))" \
        if other else "'{}'::jsonb"
    n = ctx.sql(f"INSERT zone {spec.zone_type}", f"""
        INSERT INTO core.zone (market_code, type_code, external_id, name, level_code, level_rank, geom, attrs, release_id)
        SELECT 'uk', %s, {f's."{ext_col}"::text' if ext_col else 'NULL'}, {f'nullif(s."{name_col}"::text, %s)' if name_col else 'NULL'},
               {spec.level_code or 'NULL'}, {spec.level_rank or 'NULL'}, g.geom, {attrs}, %s
        FROM {STAGE}.{t} s
        CROSS JOIN LATERAL (SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid(s.geom), 3)) AS geom) g
        WHERE {spec_where} AND NOT ST_IsEmpty(g.geom)""",
        (spec.zone_type, "", ctx.release_id) if name_col else (spec.zone_type, ctx.release_id))
    dropped = n_src - n
    if dropped > max(5, n_src * 0.01):
        # Dữ liệu dạng lưới (EA) có nhiều mảnh vụn vài m² suy biến khi làm tròn toạ độ → đánh giá theo DIỆN TÍCH bị loại
        if "shape__area" in cols and ext_col:
            # LEFT JOIN (hash anti-join) — KHÔNG dùng NOT EXISTS tương quan: 231k × 198k dòng chạy hàng giờ
            lost, total = ctx.conn.execute(f"""SELECT sum(s.shape__area) FILTER (WHERE z.external_id IS NULL),
                       sum(s.shape__area)
                FROM {STAGE}.{t} s
                LEFT JOIN (SELECT DISTINCT external_id FROM core.zone WHERE type_code = %s
                           AND release_id IS NOT DISTINCT FROM %s) z ON z.external_id = s."{ext_col}"::text
                WHERE {spec_where}""", (spec.zone_type, ctx.release_id)).fetchone()
            share = (lost or 0) / (total or 1)
            log.info("    bỏ %s feature suy biến, diện tích %.0f m² = %.5f%% tổng", dropped, lost or 0, share * 100)
            if share > 0.001:
                raise LoadError(f"{spec.file}: feature bị loại chiếm {share:.3%} diện tích (> 0,1%)")
        else:
            raise LoadError(f"{spec.file}: {dropped}/{n_src} feature không có polygon hợp lệ (> 1%)")
    # diện tích trên British National Grid (m²): ST_Area(geography) của PostGIS lỗi "area < 0" với vài polygon EA
    area = ctx.scalar("""SELECT sum(ST_Area(ST_Transform(geom, 27700))) / 1e6 FROM core.zone
                         WHERE market_code='uk' AND type_code=%s AND release_id=%s""", (spec.zone_type, ctx.release_id))
    log.info("    %s: %s polygon (bỏ %s), tổng diện tích %.0f km²", spec.zone_type, f"{n:,}", dropped, area or 0)
    if spec.area_km2 and not spec.area_km2[0] <= (area or 0) <= spec.area_km2[1]:
        raise LoadError(f"{spec.zone_type}: tổng diện tích {area:.0f} km² ngoài khoảng hợp lý {spec.area_km2}")
    ctx.stats[spec.zone_type] = n
    ctx.drop_stage(t)
    return {"polygons": n, "dropped": dropped, "area_km2": round(area or 0)}


class ZoneLoader(Loader):
    def __init__(self, source, specs, depends_on=(), description=""):
        self.source = source
        self.specs = specs
        self.depends_on = depends_on
        self.description = description or f"{source} → core.zone ({', '.join(s.zone_type for s in specs)})"

    def load(self, ctx: LoadContext) -> dict:
        out = {s.zone_type: load_zone(ctx, s) for s in self.specs}
        if self.source == "planning_data":
            out["listed_buildings"] = load_listed_buildings(ctx)
        if self.source == "planning_data_extra":
            out["brownfield_sites"] = load_brownfield(ctx)
            out["local_plans"] = load_local_plans(ctx)
        return out


def _num_sql(col: str) -> str:
    """Cột text số (planning.data để mọi giá trị dạng chuỗi) → numeric, chuỗi rỗng/lạ → NULL."""
    return f"CASE WHEN s.{col}::text ~ '^\\s*-?[0-9]+(\\.[0-9]+)?\\s*$' THEN trim(s.{col}::text)::numeric END"


def _date_sql(col: str) -> str:
    return f"CASE WHEN s.{col}::text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' THEN left(s.{col}::text, 10)::date END"


def load_brownfield(ctx: LoadContext) -> int:
    """Brownfield land register (điểm, mỗi LPA tự công bố) → core.poi planning.brownfield_site (scheme 'brownfield')."""
    t = "brownfield"
    ctx.ogr_load(str(ctx.file(r"^brownfield-land\.geojson$")), t, extra=["-nlt", "GEOMETRY"])  # điểm đến dạng MultiPoint
    cols = {r[0] for r in ctx.conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s", (STAGE, t))}
    need = {"entity", "name", "reference", "site_address", "hectares", "minimum_net_dwellings", "maximum_net_dwellings",
            "planning_permission_status", "planning_permission_type", "planning_permission_date", "ownership_status",
            "deliverable", "site_plan_url", "organisation_entity", "end_date"}
    if need - cols:
        raise LoadError(f"brownfield-land thiếu cột {sorted(need - cols)}")
    active = "(s.end_date IS NULL OR s.end_date::text = '')"
    n_src = ctx.scalar(f"SELECT count(DISTINCT s.entity) FROM {STAGE}.{t} s WHERE {active}")
    if not 15_000 <= n_src <= 60_000:
        raise LoadError(f"Số điểm brownfield bất thường: {n_src:,}")
    ctx.check_range("hecta", f"{STAGE}.{t} s", _num_sql("hectares"), 0, 1000, where=active, max_bad=int(n_src * 0.002))
    ctx.check_range("số nhà tối đa", f"{STAGE}.{t} s", _num_sql("maximum_net_dwellings"), 0, 20000, where=active,
                    max_bad=int(n_src * 0.002))
    ctx.sql("xoá brownfield cũ", "DELETE FROM core.poi WHERE market_code='uk' AND type_code='planning.brownfield_site'")
    n = ctx.sql("INSERT POI brownfield", f"""
        INSERT INTO core.poi (market_code, type_code, external_scheme, external_id, name, geom, address, status, attrs,
                              dataset_id, release_id)
        SELECT DISTINCT ON (s.entity) 'uk', 'planning.brownfield_site', 'brownfield', s.entity::text,
               coalesce(nullif(s.site_address::text, ''), nullif(s.name::text, ''), 'Brownfield site ' || s.entity),
               ST_PointOnSurface(s.geom), nullif(s.site_address::text, ''), 'open',
               jsonb_strip_nulls(jsonb_build_object(
                   'reference', nullif(s.reference::text, ''), 'hectares', {_num_sql("hectares")},
                   'min_dwellings', {_num_sql("minimum_net_dwellings")}, 'max_dwellings', {_num_sql("maximum_net_dwellings")},
                   'permission_status', nullif(s.planning_permission_status::text, ''),
                   'permission_type', nullif(s.planning_permission_type::text, ''),
                   'permission_date', {_date_sql("planning_permission_date")},
                   'ownership', nullif(s.ownership_status::text, ''), 'deliverable', nullif(s.deliverable::text, ''),
                   'site_plan_url', nullif(s.site_plan_url::text, ''), 'organisation_entity', s.organisation_entity::text)),
               'uk.mhclg.planning_data_extra', %s
        FROM {STAGE}.{t} s
        WHERE {active} AND s.geom IS NOT NULL AND ST_CoveredBy(ST_PointOnSurface(s.geom), ST_MakeEnvelope(-6.5, 49.8, 2, 56, 4326))
        ORDER BY s.entity, s.entry_date DESC NULLS LAST""", (ctx.release_id,))
    if n < 0.98 * n_src:
        raise LoadError(f"Chỉ nạp {n}/{n_src} điểm brownfield (toạ độ ngoài England?)")
    from .poi import attach_nearest_postcode
    attach_nearest_postcode(ctx, "brownfield")
    homes = ctx.scalar("""SELECT sum((attrs->>'max_dwellings')::numeric) FROM core.poi
                          WHERE market_code='uk' AND type_code='planning.brownfield_site'""")
    log.info("    brownfield: %s điểm, tối đa %s nhà", f"{n:,}", f"{homes or 0:,.0f}")
    # MHCLG: sổ brownfield ghi nhận cỡ 1–1,5 triệu nhà tiềm năng
    if not 300_000 <= (homes or 0) <= 3_000_000:
        raise LoadError(f"Tổng số nhà tiềm năng trên brownfield bất thường: {homes}")
    ctx.drop_stage(t)
    return n


LOCAL_PLAN_DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.local_plan (
    reference text PRIMARY KEY,
    name text NOT NULL,
    lpa_codes text[] NOT NULL DEFAULT '{}',
    organisation text,
    status text,
    adopted_date date,
    period_start date,
    period_end date,
    required_housing int,
    document_url text,
    documentation_url text,
    entry_date date,
    release_id bigint REFERENCES ops.dataset_release (id)
);
CREATE INDEX IF NOT EXISTS local_plan_lpa_idx ON mkt_uk.local_plan USING gin (lpa_codes);
COMMENT ON TABLE mkt_uk.local_plan IS 'Local plan của từng cơ quan quy hoạch (planning.data.gov.uk local-plan): trạng thái, ngày thông qua, giai đoạn, số nhà phải xây. lpa_codes (E60…) khớp core.zone planning.local_plan_area.external_id.'"""


def load_local_plans(ctx: LoadContext) -> int:
    import csv
    from datetime import date as _date

    def d(v):
        try:
            return _date.fromisoformat((v or "")[:10])
        except ValueError:
            return None

    def i(v):
        try:
            return int(float(v)) if v else None
        except ValueError:
            return None
    rows = []
    with open(ctx.file(r"^local-plan\.csv$"), encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        need = {"reference", "name", "end-date", "local-planning-authorities", "local-plan-boundary", "local-plan-process",
                "adopted-date", "period-start-date", "period-end-date", "required-housing", "document-url"}
        if need - set(r.fieldnames or []):
            raise LoadError(f"local-plan.csv thiếu cột {sorted(need - set(r.fieldnames or []))}")
        for row in r:
            if row.get("end-date") or not row.get("reference"):
                continue
            codes = sorted({c.strip() for c in re.split(r"[;,\s]+", (row.get("local-planning-authorities") or "") + ";" +
                                                      (row.get("local-plan-boundary") or "")) if re.fullmatch(r"E60\d{6}", c.strip())})
            rows.append((row["reference"], row["name"] or row["reference"], codes, row.get("organisation") or None,
                         row.get("local-plan-process") or None, d(row.get("adopted-date")), d(row.get("period-start-date")),
                         d(row.get("period-end-date")), i(row.get("required-housing")), row.get("document-url") or None,
                         row.get("documentation-url") or None, d(row.get("entry-date")), ctx.release_id))
    rows = list({r[0]: r for r in rows}.values())
    if not 300 <= len(rows) <= 3000:
        raise LoadError(f"Số local plan bất thường: {len(rows)}")
    with_lpa = sum(1 for r in rows if r[2]) / len(rows)
    if with_lpa < 0.8:
        raise LoadError(f"Chỉ {with_lpa:.0%} local plan có mã LPA")
    for stmt in LOCAL_PLAN_DDL.strip().split(";\n"):
        ctx.conn.execute(stmt)
    ctx.sql("TRUNCATE local_plan", "TRUNCATE mkt_uk.local_plan")
    n = ctx.copy_rows("mkt_uk.local_plan", ["reference", "name", "lpa_codes", "organisation", "status", "adopted_date",
                                            "period_start", "period_end", "required_housing", "document_url",
                                            "documentation_url", "entry_date", "release_id"], rows, "COPY local plans")
    ctx.check_range("số nhà phải xây", "mkt_uk.local_plan", "required_housing", 0, 500_000)
    # mỗi vùng local plan (E60…) phải có ít nhất một plan
    cover = ctx.scalar("""SELECT avg((EXISTS (SELECT 1 FROM mkt_uk.local_plan lp WHERE z.external_id = ANY(lp.lpa_codes)))::int)
                          FROM core.zone z WHERE z.market_code='uk' AND z.type_code='planning.local_plan_area'""")
    log.info("    local plan: %s, %.0f%% có mã LPA, %.0f%% vùng có plan", n, with_lpa * 100, (cover or 0) * 100)
    if (cover or 0) < 0.7:
        raise LoadError(f"Chỉ {cover:.0%} vùng local plan có plan tương ứng")
    return n


def load_listed_buildings(ctx: LoadContext) -> int:
    t = "listed_building"
    ctx.ogr_load(str(ctx.file(r"^listed-building\.geojson$")), t, extra=["-nlt", "GEOMETRY"])
    cols = [r[0] for r in ctx.conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s", (STAGE, t))]
    grade = _col(cols, ["listed_building_grade", "listed-building-grade", "grade"])
    if not grade:
        raise LoadError(f"listed-building: không có cột hạng (có {cols})")
    active = "(s.end_date IS NULL OR s.end_date::text = '')" if "end_date" in cols else "true"
    n_src = ctx.scalar(f"SELECT count(*) FROM {STAGE}.{t} s WHERE {active}")
    ctx.check_values_in("hạng listed building", f"{STAGE}.{t} s", f's."{grade}"', ["I", "II*", "II"], where=active)
    if not 300_000 <= n_src <= 450_000:
        raise LoadError(f"Số listed building bất thường: {n_src:,} (England có ~380 nghìn mục)")
    ctx.sql("xoá listed building cũ", "DELETE FROM core.poi WHERE market_code='uk' AND type_code='heritage.listed_building'")
    n = ctx.sql("INSERT POI listed building", f"""
        INSERT INTO core.poi (market_code, type_code, external_scheme, external_id, name, geom, status, attrs,
                              dataset_id, release_id)
        SELECT DISTINCT ON (s.reference) 'uk', 'heritage.listed_building', 'nhle', s.reference,
               coalesce(nullif(s.name, ''), 'Listed building ' || s.reference),
               ST_PointOnSurface(s.geom), 'open',
               jsonb_strip_nulls(jsonb_build_object('grade', s."{grade}", 'entity', s.entity::text,
                   'start_date', s.start_date::text, 'documentation_url', nullif(s.documentation_url::text, ''))),
               'uk.mhclg.planning_data', %s
        FROM {STAGE}.{t} s
        WHERE {active} AND s.geom IS NOT NULL AND coalesce(s.reference::text, '') <> ''
        ORDER BY s.reference, s.entity""", (ctx.release_id,))
    dist = dict(ctx.conn.execute("""SELECT attrs->>'grade', count(*) FROM core.poi
                                    WHERE type_code='heritage.listed_building' GROUP BY 1""").fetchall())
    from .poi import NEAREST_POSTCODE_SQL
    ctx.sql("gắn area_id = postcode gần nhất (listed building)", NEAREST_POSTCODE_SQL, ("nhle",))
    log.info("    listed building: %s (theo hạng %s)", f"{n:,}", dist)
    # Historic England: ~91,5% hạng II, ~5,8% II*, ~2,5% I
    share_ii = (dist.get("II") or 0) / max(n, 1)
    if not 0.85 <= share_ii <= 0.96:
        raise LoadError(f"Tỉ lệ hạng II bất thường: {share_ii:.1%} (kỳ vọng ~91%)")
    ctx.drop_stage(t)
    return n


ACTIVE = "ACTIVE"
ZONE_LOADERS = [
    ZoneLoader("police_force_areas", [
        ZoneSpec("pfa.geojson", "admin.police_force_area", name_fields=("pfa24nm", "pfa25nm", "name"),
                 ext_fields=("pfa24cd", "pfa25cd"), area_km2=(145000, 160000), min_count=43),
    ]),
    ZoneLoader("planning_data", [
        ZoneSpec("conservation-area.geojson", "planning.conservation_area", where=ACTIVE, area_km2=(500, 8000),
                 min_count=5000),
        ZoneSpec("article-4-direction-area.geojson", "planning.article4", where=ACTIVE, min_count=500),
        ZoneSpec("green-belt.geojson", "planning.green_belt", where=ACTIVE, area_km2=(10000, 22000), min_count=50),
        ZoneSpec("tree-preservation-zone.geojson", "planning.tpo", where=ACTIVE, min_count=1000),
    ], description="planning.data.gov.uk → core.zone planning.* + listed building → core.poi"),
    ZoneLoader("natural_england", [
        ZoneSpec("sssi.geojson", "nature.sssi", name_fields=("sssi_name", "name"), ext_fields=("ref_code", "objectid"),
                 area_km2=(8000, 16000), min_count=4000),
        ZoneSpec("national_parks.geojson", "nature.national_park", name_fields=("name",), ext_fields=("code", "objectid"),
                 area_km2=(10000, 14000), min_count=10),
        ZoneSpec("aonb.geojson", "nature.national_landscape", name_fields=("name",), ext_fields=("code", "objectid"),
                 area_km2=(17000, 23000), min_count=30),
        ZoneSpec("local_nature_reserves.geojson", "nature.local_nature_reserve", name_fields=("lnr_name", "name"),
                 ext_fields=("ref_code", "objectid"), min_count=1000),
    ]),
    ZoneLoader("ea_flood_zones", [
        ZoneSpec("flood_zone_3.geojson", "flood.zone3", name_fields=("type",), ext_fields=("objectid",),
                 area_km2=(5000, 25000), min_count=100000),
        ZoneSpec("flood_zone_2.geojson", "flood.zone2", name_fields=("type",), ext_fields=("objectid",),
                 area_km2=(5000, 30000), min_count=100000),
        ZoneSpec("flood_storage_areas.geojson", "flood.storage_area", name_fields=("name", "type"),
                 ext_fields=("objectid",), min_count=100),
    ]),
    ZoneLoader("ea_flood_areas", [
        ZoneSpec("flood_warning_areas.geojson", "flood.warning_area", name_fields=("label",), ext_fields=("fwdCode",),
                 area_km2=(2000, 40000), min_count=2500),
        ZoneSpec("flood_alert_areas.geojson", "flood.alert_area", name_fields=("label",), ext_fields=("fwdCode",),
                 area_km2=(10000, 120000), min_count=500),
    ], description="EA Flood Warning / Alert areas (polygon từ Flood Monitoring API) → core.zone"),
]
