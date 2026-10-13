"""OpenStreetMap UK (Geofabrik) → POI tiện ích mà nguồn nhà nước không có + đường điện cao thế.

- POI (điểm + tâm vùng): gym, trung tâm thể thao, bể bơi, thư viện, rạp chiếu phim, nhà hát, hộp đêm, trạm sạc xe điện,
  bưu điện, đồn cảnh sát, trạm cứu hoả → core.poi (external_scheme 'osm', id 'n123'/'w123'/'r123').
- Đường điện trên cao (power=line, ≥ 132 kV hoặc không ghi điện áp) → mkt_uk.power_line.
ODbL: chỉ hiển thị, ghi "© OpenStreetMap contributors"; không phát hành lại database dẫn xuất.
"""
from __future__ import annotations

import logging

from .base import STAGE, LoadContext, LoadError, Loader

log = logging.getLogger(__name__)

# (key, value) OSM → (poi type, tên mặc định)
OSM_POI = {
    ("leisure", "fitness_centre"): ("leisure.gym", "Gym"),
    ("leisure", "sports_centre"): ("leisure.sports_centre", "Sports centre"),
    ("leisure", "swimming_pool"): ("leisure.swimming_pool", "Swimming pool"),
    ("amenity", "library"): ("culture.library", "Library"),
    ("amenity", "cinema"): ("culture.cinema", "Cinema"),
    ("amenity", "theatre"): ("culture.theatre", "Theatre"),
    ("amenity", "nightclub"): ("nightlife.nightclub", "Nightclub"),
    ("amenity", "charging_station"): ("transport.ev_charging", "EV charging point"),
    ("amenity", "post_office"): ("service.post_office", "Post office"),
    ("amenity", "police"): ("emergency.police", "Police station"),
    ("amenity", "fire_station"): ("emergency.fire_station", "Fire station"),
}
POI_TYPES = {
    "leisure": "Leisure", "culture": "Culture", "nightlife": "Nightlife", "service": "Services", "emergency": "Emergency services",
    "leisure.gym": "Gym", "leisure.sports_centre": "Sports centre", "leisure.swimming_pool": "Swimming pool",
    "culture.library": "Library", "culture.cinema": "Cinema", "culture.theatre": "Theatre",
    "nightlife.nightclub": "Nightclub", "transport.ev_charging": "EV charging point", "service.post_office": "Post office",
    "emergency.police": "Police station", "emergency.fire_station": "Fire station",
}
# khoảng hợp lý số POI mỗi loại ở UK (OSM 2026)
EXPECT = {"leisure.gym": (4000, 20000), "transport.ev_charging": (4000, 80000), "culture.library": (2500, 6000),
          "service.post_office": (6000, 13000), "emergency.fire_station": (1000, 2500)}

POWER_DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.power_line (
    osm_id bigint PRIMARY KEY, voltage_kv real, operator text, geom geometry(MultiLineString, 4326) NOT NULL,
    release_id bigint REFERENCES ops.dataset_release (id)
);
CREATE INDEX IF NOT EXISTS power_line_geom ON mkt_uk.power_line USING gist (geom);
COMMENT ON TABLE mkt_uk.power_line IS 'Đường điện trên cao (OSM power=line, ≥ 132 kV hoặc không ghi điện áp), © OpenStreetMap contributors (ODbL).'"""


def tag(col: str, key: str) -> str:
    """Giá trị tag trong cột other_tags của GDAL OSM ("k"=>"v","k2"=>"v2")."""
    return f"substring({col} from '\"{key}\"=>\"([^\"]*)\"')"


class OsmLoader(Loader):
    source = "osm_uk"
    depends_on = ("onspd",)
    description = "OSM UK → core.poi (gym, bể bơi, thư viện, rạp, trạm sạc EV, bưu điện, cảnh sát, cứu hoả) + mkt_uk.power_line"

    def load(self, ctx: LoadContext) -> dict:
        pbf = str(ctx.file(r"\.osm\.pbf$"))
        conds = " OR ".join(f"other_tags LIKE '%\"{k}\"=>\"{v}\"%'" for k, v in OSM_POI)
        ctx.ogr_load(pbf, "osm_pt", extra=[
            "-nlt", "MULTIPOINT", "-sql", f"SELECT osm_id, name, other_tags FROM points WHERE {conds}"])
        ctx.ogr_load(pbf, "osm_poly", extra=[
            "-nlt", "MULTIPOLYGON", "-sql",
            f"SELECT osm_id, osm_way_id, name, leisure, amenity, other_tags FROM multipolygons "
            f"WHERE leisure IN ('fitness_centre','sports_centre','swimming_pool') OR amenity IN "
            f"({', '.join(repr(v) for k, v in OSM_POI if k == 'amenity')})"])
        ctx.ogr_load(pbf, "osm_power", extra=[
            "-nlt", "MULTILINESTRING", "-sql", "SELECT osm_id, other_tags FROM lines WHERE other_tags LIKE '%\"power\"=>\"line\"%'"])

        case_pt = "CASE " + " ".join(f"WHEN other_tags LIKE '%\"{k}\"=>\"{v}\"%' THEN '{t}'" for (k, v), (t, _) in OSM_POI.items()) + " END"
        case_poly = "CASE " + " ".join(f"WHEN {k} = '{v}' THEN '{t}'" for (k, v), (t, _) in OSM_POI.items()) + " END"
        # bể bơi riêng (nhà dân) không phải tiện ích công cộng: chỉ giữ khi access không phải private
        priv = f"coalesce({tag('other_tags', 'access')}, '') IN ('private', 'no', 'customers')"
        ctx.sql("POI OSM gộp (điểm + tâm vùng)", f"""
            CREATE TEMP TABLE osm_poi ON COMMIT DROP AS
            SELECT 'n' || osm_id AS ext, name, {case_pt} AS type_code, ST_GeometryN(geom, 1) AS geom,
                   {tag('other_tags', 'operator')} AS operator, {tag('other_tags', 'brand')} AS brand,
                   {tag('other_tags', 'opening_hours')} AS opening_hours, {tag('other_tags', 'website')} AS website,
                   {tag('other_tags', 'capacity')} AS capacity, {priv} AS is_private
            FROM {STAGE}.osm_pt
            UNION ALL
            SELECT CASE WHEN osm_way_id IS NOT NULL THEN 'w' || osm_way_id ELSE 'r' || osm_id END, name, {case_poly},
                   ST_PointOnSurface(geom), {tag('other_tags', 'operator')}, {tag('other_tags', 'brand')},
                   {tag('other_tags', 'opening_hours')}, {tag('other_tags', 'website')}, {tag('other_tags', 'capacity')},
                   {priv}
            FROM {STAGE}.osm_poly""")
        ctx.sql("bỏ POI riêng tư / không xác định loại", "DELETE FROM osm_poi WHERE type_code IS NULL OR is_private OR geom IS NULL")
        # bể bơi trong vườn nhà thường không có tên và không ghi access → chỉ giữ bể có tên (bể công cộng, trung tâm thể thao)
        ctx.sql("bỏ bể bơi không tên", "DELETE FROM osm_poi WHERE type_code = 'leisure.swimming_pool' AND coalesce(name, '') = ''")
        values = ", ".join(f"('{c}', {('NULL' if '.' not in c else repr(c.split('.')[0]))}, '{{\"en\":\"{n}\"}}')"
                           for c, n in POI_TYPES.items() if c != "transport")
        ctx.conn.execute(f"""INSERT INTO core.poi_type (code, parent_code, name_i18n, is_searchable, has_pages, url_segment)
            SELECT v.code, v.parent, v.name::jsonb, false, false, NULL FROM (VALUES {values}) v(code, parent, name)
            ORDER BY v.parent NULLS FIRST
            ON CONFLICT (code) DO NOTHING""")
        counts = dict(ctx.conn.execute("SELECT type_code, count(*) FROM osm_poi GROUP BY 1").fetchall())
        log.info("    POI OSM theo loại: %s", counts)
        for t, (lo, hi) in EXPECT.items():
            if not lo <= counts.get(t, 0) <= hi:
                raise LoadError(f"Số POI {t} bất thường: {counts.get(t, 0)} (kỳ vọng {lo}–{hi})")
        n = ctx.sql("upsert core.poi (osm)", """
            INSERT INTO core.poi (market_code, type_code, external_scheme, external_id, name, geom, status, attrs,
                                  dataset_id, release_id)
            SELECT DISTINCT ON (ext) 'uk', type_code, 'osm', ext, coalesce(nullif(name, ''), nullif(brand, ''), %s::jsonb ->> type_code),
                   geom, 'open', jsonb_strip_nulls(jsonb_build_object('operator', operator, 'brand', brand,
                   'opening_hours', opening_hours, 'website', website, 'capacity', capacity)), 'uk.osm.geofabrik', %s
            FROM osm_poi ORDER BY ext
            ON CONFLICT (market_code, external_scheme, external_id) DO UPDATE SET type_code = EXCLUDED.type_code,
                name = EXCLUDED.name, geom = EXCLUDED.geom, status = 'open', attrs = EXCLUDED.attrs,
                release_id = EXCLUDED.release_id""",
                    (__import__("json").dumps({t: nm for (_, _), (t, nm) in OSM_POI.items()}), ctx.release_id))
        closed = ctx.sql("POI OSM không còn → closed", """UPDATE core.poi SET status = 'closed'
            WHERE market_code='uk' AND external_scheme='osm' AND release_id IS DISTINCT FROM %s AND status = 'open'""",
                         (ctx.release_id,))
        from .poi import attach_nearest_postcode
        attach_nearest_postcode(ctx, "osm")

        # ---- đường điện cao thế
        for stmt in POWER_DDL.strip().split(";\n"):
            ctx.conn.execute(stmt)
        ctx.sql("TRUNCATE power_line", "TRUNCATE mkt_uk.power_line")
        v = tag("other_tags", "voltage")
        p = ctx.sql("INSERT power_line", f"""
            INSERT INTO mkt_uk.power_line (osm_id, voltage_kv, operator, geom, release_id)
            SELECT DISTINCT ON (osm_id) osm_id::bigint,
                   CASE WHEN split_part({v}, ';', 1) ~ '^[0-9]+$' THEN split_part({v}, ';', 1)::real / 1000 END,
                   {tag('other_tags', 'operator')}, ST_Multi(geom), %s
            FROM {STAGE}.osm_power
            WHERE geom IS NOT NULL AND (split_part({v}, ';', 1) !~ '^[0-9]+$' OR split_part({v}, ';', 1)::real >= 132000)
            ORDER BY osm_id""", (ctx.release_id,))
        km = ctx.scalar("SELECT sum(ST_Length(geom::geography)) / 1000 FROM mkt_uk.power_line WHERE voltage_kv >= 275")
        log.info("    đường điện: %s đoạn, %.0f km ≥ 275 kV (lưới truyền tải National Grid ~ 7–8 nghìn km trên cao)", p, km or 0)
        if not 3000 <= (km or 0) <= 15000:
            raise LoadError(f"Chiều dài lưới ≥ 275 kV bất thường: {km}")
        ctx.drop_stage("osm_pt", "osm_poly", "osm_power")
        return {"poi": n, "closed": closed, "by_type": counts, "power_lines": p, "km_275kv": round(km or 0)}
