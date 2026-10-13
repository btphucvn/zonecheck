"""Nạp OS Open Names (khu dân cư → geo_area level town) và OS Open Greenspace (→ core.zone greenspace.*)."""
from __future__ import annotations

import csv
import io
import logging
import zipfile

from .base import STAGE, LoadContext, LoadError, Loader, slug_sql

log = logging.getLogger(__name__)

# LOCAL_TYPE của populatedPlace được làm trang town. Hamlet/Other Settlement quá nhỏ → bỏ.
TOWN_TYPES = ("City", "Town", "Village", "Suburban Area")


class OpenNamesLoader(Loader):
    source = "os_open_names"
    depends_on = ("boundaries_lad",)
    description = "OS Open Names (City/Town/Village/Suburban Area) → core.geo_area level town (+ liên kết town → lad)"

    def load(self, ctx: LoadContext) -> dict:
        z = ctx.file(r"\.zip$")
        with zipfile.ZipFile(z) as zf:
            header = zf.read("Doc/OS_Open_Names_Header.csv").decode("utf-8-sig").strip().split(",")
            members = sorted(n for n in zf.namelist() if n.startswith("Data/") and n.endswith(".csv"))
            t = ctx.stage_table("open_names", header)
            # chỉ giữ populatedPlace để stage nhỏ (file gốc ~3 triệu dòng, phần lớn là đường)
            def rows():
                for m in members:
                    with zf.open(m) as f:
                        for r in csv.reader(io.TextIOWrapper(f, encoding="utf-8", newline="")):
                            if len(r) != len(header):
                                raise LoadError(f"{m}: dòng có {len(r)} cột, header có {len(header)}: {r[:5]}")
                            if r[6] == "populatedPlace":
                                yield r
            n = ctx.copy_rows(t, header, rows(), f"COPY populatedPlace từ {len(members)} file")
        types = ctx.conn.execute(f'SELECT "LOCAL_TYPE", count(*) FROM {t} GROUP BY 1 ORDER BY 2 DESC').fetchall()
        log.info("    LOCAL_TYPE: %s", types)
        keep = f""""LOCAL_TYPE" IN ({", ".join(f"'{x}'" for x in TOWN_TYPES)})"""
        expected = ctx.scalar(f"SELECT count(*) FROM {t} WHERE {keep}")
        name = 'coalesce(nullif("NAME1", \'\'), "NAME2")'
        county = 'coalesce(nullif("COUNTY_UNITARY", \'\'), nullif("DISTRICT_BOROUGH", \'\'), "REGION")'
        ctx.sql("upsert geo_area town", f"""
            INSERT INTO core.geo_area (market_code, level_code, code, slug, name, name_i18n, display_name, centroid,
                                       is_active, attrs)
            SELECT 'uk', 'town', s."ID", s.slug, s.name, s.name_i18n, s.display_name, s.pt, true, s.attrs
            FROM (
                SELECT "ID", {name} AS name,
                       CASE WHEN nullif("NAME2", '') IS NOT NULL
                            THEN jsonb_build_object(coalesce(nullif("NAME2_LANG", ''), 'cy'), "NAME2") ELSE '{{}}'::jsonb END AS name_i18n,
                       {name} || ', ' || {county} AS display_name,
                       ST_Transform(ST_SetSRID(ST_MakePoint("GEOMETRY_X"::float8, "GEOMETRY_Y"::float8), 27700), 4326) AS pt,
                       -- slug theo tên; tên trùng (Newport, Richmond...) → tên-hạt, vẫn trùng → thêm ID
                       CASE WHEN count(*) OVER (PARTITION BY {slug_sql(name)}) = 1 THEN {slug_sql(name)}
                            WHEN count(*) OVER (PARTITION BY {slug_sql(name)}, {slug_sql(county)}) = 1
                                 THEN {slug_sql(name)} || '-' || {slug_sql(county)}
                            ELSE {slug_sql(name)} || '-' || {slug_sql(county)} || '-' || lower("ID") END AS slug,
                       jsonb_strip_nulls(jsonb_build_object('local_type', "LOCAL_TYPE",
                           'postcode_district', nullif("POSTCODE_DISTRICT", ''),
                           'district_borough', nullif("DISTRICT_BOROUGH", ''), 'county_unitary', nullif("COUNTY_UNITARY", ''),
                           'region', nullif("REGION", ''), 'country', nullif("COUNTRY", ''),
                           'bbox_bng', jsonb_build_array("MBR_XMIN", "MBR_YMIN", "MBR_XMAX", "MBR_YMAX"),
                           'os_uri', "NAMES_URI")) AS attrs
                FROM {t} WHERE {keep}) s
            ON CONFLICT (market_code, level_code, code) DO UPDATE SET name = EXCLUDED.name, slug = EXCLUDED.slug,
                name_i18n = EXCLUDED.name_i18n, display_name = EXCLUDED.display_name, centroid = EXCLUDED.centroid,
                is_active = true, attrs = EXCLUDED.attrs""")
        n_db = ctx.scalar("SELECT count(*) FROM core.geo_area WHERE market_code='uk' AND level_code='town' AND is_active")
        ctx.expect("geo_area town", n_db, expected)
        ctx.sql("liên kết town → lad (điểm nằm trong LAD)", """
            INSERT INTO core.geo_area_link (child_id, parent_id, relation, weight, weight_basis)
            SELECT t.id, l.id, 'within', 1, 'none'
            FROM core.geo_area t JOIN core.geo_area l ON l.market_code='uk' AND l.level_code='lad' AND l.is_active
                 AND ST_Intersects(l.geom, t.centroid)
            WHERE t.market_code='uk' AND t.level_code='town'
            ON CONFLICT DO NOTHING""")
        ctx.drop_stage("open_names")
        return {"populated_places": n, "towns": n_db}


GREENSPACE_TYPES = {
    "Public Park Or Garden": "greenspace.park",
    "Play Space": "greenspace.play",
    "Playing Field": "greenspace.playing_field",
    "Other Sports Facility": "greenspace.sports",
    "Bowling Green": "greenspace.sports",
    "Tennis Court": "greenspace.sports",
    "Allotments Or Community Growing Spaces": "greenspace.allotment",
    "Cemetery": "greenspace.cemetery",
    "Religious Grounds": "greenspace.cemetery",
    "Golf Course": "greenspace.golf",
}


class GreenspaceLoader(Loader):
    source = "os_open_greenspace"
    description = "OS Open Greenspace (greenspace_site) → core.zone greenspace.* (thay toàn bộ mỗi lần nạp)"

    def load(self, ctx: LoadContext) -> dict:
        z = ctx.file(r"\.zip$")
        gpkg = "/vsizip/" + str(z) + "/Data/opgrsp_gb.gpkg"
        ctx.ogr_load(gpkg, "greenspace", layer="greenspace_site")
        t = f"{STAGE}.greenspace"
        n = ctx.scalar(f"SELECT count(*) FROM {t}")
        unknown = ctx.conn.execute(f"SELECT function, count(*) FROM {t} WHERE NOT (function = ANY(%s)) GROUP BY 1",
                                   (list(GREENSPACE_TYPES),)).fetchall()
        if unknown:
            raise LoadError(f"Loại greenspace chưa ánh xạ: {unknown} — thêm vào GREENSPACE_TYPES")
        mapping = "CASE g.function " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in GREENSPACE_TYPES.items()) + " END"
        types = sorted(set(GREENSPACE_TYPES.values()))
        ctx.sql("xoá greenspace cũ", "DELETE FROM core.zone WHERE market_code='uk' AND type_code = ANY(%s)", (types,))
        ctx.sql("INSERT core.zone greenspace", f"""
            INSERT INTO core.zone (market_code, type_code, external_id, name, geom, attrs, release_id)
            SELECT 'uk', {mapping}, g.id, nullif(g.distinctive_name_1, ''),
                   ST_Multi(ST_CollectionExtract(ST_MakeValid(g.geom), 3)),
                   jsonb_strip_nulls(jsonb_build_object('function', g.function,
                       'other_names', nullif(concat_ws('; ', nullif(g.distinctive_name_2, ''),
                           nullif(g.distinctive_name_3, ''), nullif(g.distinctive_name_4, '')), ''))), %s
            FROM {t} g""", (ctx.release_id,))
        n_db = ctx.scalar("SELECT count(*) FROM core.zone WHERE market_code='uk' AND type_code = ANY(%s)", (types,))
        ctx.expect("core.zone greenspace", n_db, n)
        ctx.drop_stage("greenspace")
        return {"sites": n}
