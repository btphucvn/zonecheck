"""Nạp địa lý: ranh giới ONS → core.geo_area; ONSPD → mkt_uk.postcode + postcode/sector/district/area + liên kết cấp."""
from __future__ import annotations

import logging
import re

from .base import STAGE, LoadContext, LoadError, Loader, slug_sql, zip_members

log = logging.getLogger(__name__)

NATIONS = {  # mã ONS nation, tên, tiền tố mã LAD
    "E92000001": ("England", "E"),
    "W92000004": ("Wales", "W"),
    "S92000003": ("Scotland", "S"),
    "N92000002": ("Northern Ireland", "N"),
}


class BoundaryLoader(Loader):
    """Một file GeoJSON ranh giới → core.geo_area (level tương ứng)."""

    def __init__(self, source: str, level: str, code_prefix: str, slug_by_name: bool):
        self.source = source
        self.level = level
        self.code_prefix = code_prefix  # OA, LSOA, MSOA, LAD, RGN
        self.slug_by_name = slug_by_name
        self.description = f"{source} → core.geo_area(level={level})"

    def load(self, ctx: LoadContext) -> dict:
        src = ctx.file(r"\.geojson$")
        t = f"b_{self.level}"
        ctx.ogr_load(str(src), t)
        cols = [r[0] for r in ctx.conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
            (STAGE, t)).fetchall()]
        code_col = _pick(cols, rf"^{self.code_prefix.lower()}\d\dcd$")
        name_col = _pick(cols, rf"^{self.code_prefix.lower()}\d\dnm$", required=self.level != "oa") or code_col
        log.info("    cột mã=%s, cột tên=%s", code_col, name_col)

        ctx.conn.execute(f"CREATE INDEX ON {STAGE}.{t} ({code_col})")
        n_src = ctx.scalar(f"SELECT count(*) FROM {STAGE}.{t}")
        expected = ctx.manifest.get("row_count") or n_src
        ctx.expect("số feature trong file", n_src, expected)
        dup = ctx.scalar(f"SELECT count(*) - count(DISTINCT {code_col}) FROM {STAGE}.{t}")
        if dup:
            raise LoadError(f"{dup} mã {code_col} bị trùng trong {src.name}")

        slug = slug_sql(name_col) if self.slug_by_name else f"lower({code_col})"
        simplify = "ST_Multi(ST_SimplifyPreserveTopology(g.geom, 0.0005))" if self.level in ("lad", "region") else "NULL"
        ctx.sql("upsert core.geo_area", f"""
            INSERT INTO core.geo_area (market_code, level_code, code, slug, name, geom, geom_simplified, centroid,
                                       area_km2, is_active, attrs)
            SELECT 'uk', %(level)s, g.code, g.slug, g.name, g.geom, {simplify},
                   ST_PointOnSurface(g.geom), ST_Area(g.geom::geography) / 1e6, true,
                   jsonb_build_object('source_release', %(release)s)
            FROM (SELECT code, name, geom,
                         -- trùng slug theo tên (hiếm) → thêm mã cho các bản trùng
                         CASE WHEN count(*) OVER (PARTITION BY slug0) > 1 THEN slug0 || '-' || lower(code)
                              ELSE slug0 END AS slug
                  FROM (SELECT {code_col} AS code, {name_col} AS name, {slug} AS slug0,
                               ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 3)) AS geom
                        FROM {STAGE}.{t}) a) g
            ON CONFLICT (market_code, level_code, code) DO UPDATE SET
                name = EXCLUDED.name, slug = EXCLUDED.slug, geom = EXCLUDED.geom,
                geom_simplified = EXCLUDED.geom_simplified, centroid = EXCLUDED.centroid,
                area_km2 = EXCLUDED.area_km2, is_active = true, valid_to = NULL,
                attrs = core.geo_area.attrs || EXCLUDED.attrs
        """, {"level": self.level, "release": ctx.release_id})
        retired = ctx.sql("đánh dấu mã không còn trong bản mới", f"""
            UPDATE core.geo_area a SET is_active = false, valid_to = current_date
            WHERE a.market_code = 'uk' AND a.level_code = %s AND a.is_active
              AND NOT EXISTS (SELECT 1 FROM {STAGE}.{t} s WHERE s.{code_col} = a.code)""", (self.level,))
        n_db = ctx.scalar("SELECT count(*) FROM core.geo_area WHERE market_code='uk' AND level_code=%s AND is_active",
                          (self.level,))
        ctx.expect(f"geo_area {self.level} đang hoạt động", n_db, n_src)

        if self.level == "oa":  # file OA có sẵn mã LSOA cha
            ctx.sql("liên kết oa → lsoa", f"""
                INSERT INTO core.geo_area_link (child_id, parent_id, relation, weight, weight_basis)
                SELECT c.id, p.id, 'within', 1, 'none'
                FROM {STAGE}.{t} s
                JOIN core.geo_area c ON c.market_code='uk' AND c.level_code='oa' AND c.code = s.{code_col}
                JOIN core.geo_area p ON p.market_code='uk' AND p.level_code='lsoa' AND p.code = s.lsoa21cd
                ON CONFLICT DO NOTHING""")
        if self.level == "lad":
            _build_nations(ctx)
        ctx.drop_stage(t)
        return {"features": n_src, "retired": retired}


def _pick(cols: list[str], pattern: str, required: bool = True) -> str | None:
    hits = [c for c in cols if re.match(pattern, c)]
    if len(hits) != 1:
        if not required and not hits:
            return None
        raise LoadError(f"Không xác định được cột theo {pattern}: thấy {hits} trong {cols}")
    return hits[0]


def _build_nations(ctx: LoadContext) -> None:
    """Nation = gộp các LAD theo tiền tố mã (E/W/S/N); liên kết lad → nation."""
    for code, (name, prefix) in NATIONS.items():
        ctx.sql(f"nation {name}", """
            INSERT INTO core.geo_area (market_code, level_code, code, slug, name, geom, geom_simplified, centroid, area_km2)
            SELECT 'uk', 'nation', %(code)s, %(slug)s, %(name)s, u.geom,
                   ST_Multi(ST_SimplifyPreserveTopology(u.geom, 0.002)), ST_PointOnSurface(u.geom),
                   ST_Area(u.geom::geography) / 1e6
            FROM (SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Union(geom_simplified)), 3)) AS geom
                  FROM core.geo_area WHERE market_code='uk' AND level_code='lad' AND is_active AND code LIKE %(p)s) u
            WHERE u.geom IS NOT NULL
            ON CONFLICT (market_code, level_code, code) DO UPDATE SET geom = EXCLUDED.geom,
                geom_simplified = EXCLUDED.geom_simplified, centroid = EXCLUDED.centroid, area_km2 = EXCLUDED.area_km2
        """, {"code": code, "slug": name.lower().replace(" ", "-"), "name": name, "p": prefix + "%"})
    ctx.sql("liên kết lad → nation", """
        INSERT INTO core.geo_area_link (child_id, parent_id, relation, weight, weight_basis)
        SELECT l.id, n.id, 'within', 1, 'none'
        FROM core.geo_area l
        JOIN core.geo_area n ON n.market_code='uk' AND n.level_code='nation'
         AND left(n.code, 1) = left(l.code, 1)
        WHERE l.market_code='uk' AND l.level_code='lad' AND l.is_active
        ON CONFLICT DO NOTHING""")


class WardLoader(BoundaryLoader):
    """Ward bầu cử (E&W) → core.geo_area level 'ward'. Slug = tên ward + tên LAD (tên ward trùng nhau giữa các LAD),
    liên kết ward → LAD theo LAD của đa số postcode trong ward (ONSPD)."""

    def __init__(self):
        super().__init__("boundaries_ward", "ward", "WD", True)
        self.depends_on = ("boundaries_lad", "onspd")

    def load(self, ctx: LoadContext) -> dict:
        src = ctx.file(r"\.geojson$")
        t = "b_ward"
        ctx.ogr_load(str(src), t)
        cols = [r[0] for r in ctx.conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s", (STAGE, t)).fetchall()]
        code_col = _pick(cols, r"^wd\d\dcd$")
        name_col = _pick(cols, r"^wd\d\dnm$")
        removed = ctx.sql("bỏ ward Scotland/Bắc Ireland", f"DELETE FROM {STAGE}.{t} WHERE left({code_col}, 1) NOT IN ('E', 'W')")
        n_src = ctx.scalar(f"SELECT count(*) FROM {STAGE}.{t}")
        if not 7000 <= n_src <= 8500:
            raise LoadError(f"Số ward E&W bất thường: {n_src}")
        # LAD của từng ward theo đa số postcode đang dùng
        ctx.sql("LAD của ward", f"""
            CREATE TEMP TABLE ward_lad ON COMMIT DROP AS
            SELECT DISTINCT ON (ward_code) ward_code, lad_code FROM (
                SELECT ward_code, lad_code, count(*) n FROM mkt_uk.postcode
                WHERE status = 'live' AND left(ward_code, 1) IN ('E', 'W') GROUP BY 1, 2) x
            ORDER BY ward_code, n DESC""")
        match = ctx.scalar(f"SELECT avg((w.ward_code IS NOT NULL)::int)::float8 FROM {STAGE}.{t} s LEFT JOIN ward_lad w ON w.ward_code = s.{code_col}")
        log.info("    %.1f%% ward khớp mã ward trong ONSPD", (match or 0) * 100)
        if (match or 0) < 0.97:
            raise LoadError(f"Chỉ {match:.1%} ward khớp ONSPD — phiên bản ranh giới khác phiên bản mã của ONSPD")
        ctx.sql("upsert core.geo_area ward", f"""
            INSERT INTO core.geo_area (market_code, level_code, code, slug, name, geom, geom_simplified, centroid, area_km2, is_active, attrs)
            SELECT 'uk', 'ward', g.code, g.slug, g.name, g.geom, ST_Multi(ST_SimplifyPreserveTopology(g.geom, 0.0002)),
                   ST_PointOnSurface(g.geom), ST_Area(g.geom::geography) / 1e6, true,
                   jsonb_build_object('source_release', %(release)s, 'lad_code', g.lad_code)
            FROM (SELECT code, name, geom, lad_code,
                         CASE WHEN count(*) OVER (PARTITION BY slug0) > 1 THEN slug0 || '-' || lower(code) ELSE slug0 END AS slug
                  FROM (SELECT s.{code_col} AS code, s.{name_col} AS name, w.lad_code,
                               {slug_sql(f"s.{name_col} || ' ' || coalesce(l.name, '')")} AS slug0,
                               ST_Multi(ST_CollectionExtract(ST_MakeValid(s.geom), 3)) AS geom
                        FROM {STAGE}.{t} s LEFT JOIN ward_lad w ON w.ward_code = s.{code_col}
                        LEFT JOIN core.geo_area l ON l.market_code = 'uk' AND l.level_code = 'lad' AND l.code = w.lad_code) a) g
            ON CONFLICT (market_code, level_code, code) DO UPDATE SET
                name = EXCLUDED.name, slug = EXCLUDED.slug, geom = EXCLUDED.geom, geom_simplified = EXCLUDED.geom_simplified,
                centroid = EXCLUDED.centroid, area_km2 = EXCLUDED.area_km2, is_active = true, valid_to = NULL,
                attrs = core.geo_area.attrs || EXCLUDED.attrs""", {"release": ctx.release_id})
        retired = ctx.sql("ward không còn trong bản mới", f"""
            UPDATE core.geo_area a SET is_active = false, valid_to = current_date
            WHERE a.market_code = 'uk' AND a.level_code = 'ward' AND a.is_active
              AND NOT EXISTS (SELECT 1 FROM {STAGE}.{t} s WHERE s.{code_col} = a.code)""")
        ctx.sql("liên kết ward → lad", """
            INSERT INTO core.geo_area_link (child_id, parent_id, relation, weight, weight_basis)
            SELECT w.id, l.id, 'within', 1, 'none' FROM core.geo_area w
            JOIN core.geo_area l ON l.market_code = 'uk' AND l.level_code = 'lad' AND l.code = w.attrs->>'lad_code'
            WHERE w.market_code = 'uk' AND w.level_code = 'ward' AND w.is_active
            ON CONFLICT DO NOTHING""")
        n_db = ctx.scalar("SELECT count(*) FROM core.geo_area WHERE market_code='uk' AND level_code='ward' AND is_active")
        ctx.expect("geo_area ward đang hoạt động", n_db, n_src)
        ctx.drop_stage(t)
        return {"features": n_src, "removed_non_ew": removed, "retired": retired, "onspd_match": round(match, 4)}


BOUNDARY_LOADERS = [
    BoundaryLoader("boundaries_rgn", "region", "RGN", True),
    BoundaryLoader("boundaries_lad", "lad", "LAD", True),
    BoundaryLoader("boundaries_msoa21", "msoa", "MSOA", False),
    BoundaryLoader("boundaries_lsoa21", "lsoa", "LSOA", False),
    BoundaryLoader("boundaries_oa21", "oa", "OA", False),
]
WARD_LOADER = WardLoader()
BOUNDARY_LOADERS[4].depends_on = ("boundaries_lsoa21",)  # cần LSOA để liên kết oa → lsoa


class OnspdLoader(Loader):
    source = "onspd"
    depends_on = ("boundaries_oa21", "boundaries_lsoa21", "boundaries_msoa21", "boundaries_lad", "boundaries_rgn")
    description = ("ONSPD → mkt_uk.postcode; core.geo_area postcode_unit/sector/district/postal_area; "
                   "liên kết postcode→sector→district→area, postcode→oa, lsoa→msoa→lad→region")

    def load(self, ctx: LoadContext) -> dict:
        z = ctx.file(r"^ONSPD_.*\.zip$")
        members = zip_members(z, r"Data/multi_csv/ONSPD_.*\.csv$")
        if not members:
            raise LoadError(f"Không thấy Data/multi_csv/*.csv trong {z.name}")
        import io
        import zipfile
        with zipfile.ZipFile(z) as zf:
            header = zf.open(members[0]).readline().decode("utf-8-sig").strip().split(",")
            t = ctx.stage_table("onspd", header)
            total = 0
            for m in members:
                with zf.open(m) as f:
                    total += ctx.copy_csv(t, io.BufferedReader(f), header=True, analyze=False,
                                          label=f"COPY {m.rsplit('/', 1)[-1]}")
        ctx.conn.execute(f"ANALYZE {t}")
        log.info("    tổng %s dòng từ %s file", f"{total:,}", len(members))
        ctx.stats["onspd_rows"] = total

        c = {k: _pick(header, p) for k, p in {
            "lad": r"^lad\d\dcd$", "wd": r"^wd\d\dcd$", "ctry": r"^ctry\d\dcd$", "rgn": r"^rgn\d\dcd$"}.items()}
        log.info("    cột năm hiện hành: %s", c)
        ctx.conn.execute(f"CREATE INDEX ON {t} (pcds)")

        ctx.sql("upsert mkt_uk.postcode", f"""
            INSERT INTO mkt_uk.postcode (postcode, postcode_compact, sector, district, postal_area, status,
                introduced_on, terminated_on, country_code, region_code, lad_code, ward_code, oa21_code,
                lsoa21_code, msoa21_code, positional_quality, geom, release_id)
            SELECT pcds, replace(pcds, ' ', ''), left(pcds, length(pcds) - 2), split_part(pcds, ' ', 1),
                   substring(pcds from '^[A-Z]+'),
                   CASE WHEN nullif(doterm, '') IS NULL THEN 'live' ELSE 'terminated' END,
                   to_date(nullif(dointr, ''), 'YYYYMM'), to_date(nullif(doterm, ''), 'YYYYMM'),
                   {c['ctry']}, nullif({c['rgn']}, ''), nullif({c['lad']}, ''), nullif({c['wd']}, ''),
                   nullif(oa21cd, ''), nullif(lsoa21cd, ''), nullif(msoa21cd, ''), nullif(gridind, '')::smallint,
                   CASE WHEN lat::numeric BETWEEN 49 AND 61 THEN ST_SetSRID(ST_MakePoint(long::float8, lat::float8), 4326) END,
                   %(rel)s
            FROM {t}
            ON CONFLICT (postcode) DO UPDATE SET status = EXCLUDED.status, terminated_on = EXCLUDED.terminated_on,
                country_code = EXCLUDED.country_code, region_code = EXCLUDED.region_code, lad_code = EXCLUDED.lad_code,
                ward_code = EXCLUDED.ward_code, oa21_code = EXCLUDED.oa21_code, lsoa21_code = EXCLUDED.lsoa21_code,
                msoa21_code = EXCLUDED.msoa21_code, positional_quality = EXCLUDED.positional_quality,
                geom = EXCLUDED.geom, release_id = EXCLUDED.release_id
        """, {"rel": ctx.release_id})
        n_pc = ctx.scalar("SELECT count(*) FROM mkt_uk.postcode")
        ctx.expect("mkt_uk.postcode", n_pc, total, tolerance=0.001)

        # --- postcode_unit: mọi postcode có toạ độ; postcode đã ngừng → is_active=false (dùng cho redirect 301)
        ctx.sql("geo_area postcode_unit", """
            INSERT INTO core.geo_area (market_code, level_code, code, slug, name, centroid, is_active, valid_from, valid_to)
            SELECT 'uk', 'postcode_unit', p.postcode, lower(replace(p.postcode, ' ', '-')), p.postcode, p.geom,
                   p.status = 'live', p.introduced_on, p.terminated_on
            FROM mkt_uk.postcode p WHERE p.geom IS NOT NULL
            ON CONFLICT (market_code, level_code, code) DO UPDATE SET centroid = EXCLUDED.centroid,
                is_active = EXCLUDED.is_active, valid_to = EXCLUDED.valid_to""")
        for level, col in (("sector", "sector"), ("district", "district"), ("postal_area", "postal_area")):
            ctx.sql(f"geo_area {level}", f"""
                INSERT INTO core.geo_area (market_code, level_code, code, slug, name, centroid, is_active, attrs)
                SELECT 'uk', %(level)s, {col}, lower(replace({col}, ' ', '-')), {col},
                       ST_Centroid(ST_Collect(geom)), bool_or(status = 'live'),
                       jsonb_build_object('live_postcodes', count(*) FILTER (WHERE status = 'live'))
                FROM mkt_uk.postcode WHERE geom IS NOT NULL AND {col} IS NOT NULL
                GROUP BY {col}
                ON CONFLICT (market_code, level_code, code) DO UPDATE SET centroid = EXCLUDED.centroid,
                    is_active = EXCLUDED.is_active, attrs = core.geo_area.attrs || EXCLUDED.attrs""",
                {"level": level})
        ctx.sql("gắn mkt_uk.postcode.area_id", """
            UPDATE mkt_uk.postcode p SET area_id = a.id
            FROM core.geo_area a
            WHERE a.market_code='uk' AND a.level_code='postcode_unit' AND a.code = p.postcode
              AND p.area_id IS DISTINCT FROM a.id""")

        # --- liên kết cấp (postal lồng nhau hoàn toàn; thống kê dùng nhóm đa số theo ONSPD)
        link = """
            INSERT INTO core.geo_area_link (child_id, parent_id, relation, weight, weight_basis)
            SELECT c.id, p.id, %(rel)s, %(w)s, %(basis)s
            FROM ({pairs}) x
            JOIN core.geo_area c ON c.market_code='uk' AND c.level_code=%(cl)s AND c.code = x.child
            JOIN core.geo_area p ON p.market_code='uk' AND p.level_code=%(pl)s AND p.code = x.parent
            ON CONFLICT DO NOTHING"""
        within = dict(rel="within", w=1, basis="none")
        steps = [
            ("postcode_unit", "sector", "SELECT postcode AS child, sector AS parent FROM mkt_uk.postcode"),
            ("sector", "district", "SELECT DISTINCT sector AS child, district AS parent FROM mkt_uk.postcode"),
            ("district", "postal_area", "SELECT DISTINCT district AS child, postal_area AS parent FROM mkt_uk.postcode"),
            ("postcode_unit", "oa", "SELECT postcode AS child, oa21_code AS parent FROM mkt_uk.postcode WHERE oa21_code IS NOT NULL"),
        ]
        for cl, pl, pairs in steps:
            ctx.sql(f"liên kết {cl} → {pl}", link.format(pairs=pairs), {**within, "cl": cl, "pl": pl})
        # LSOA/MSOA lồng trong LAD theo thiết kế ONS; lấy cha đa số theo số postcode đang dùng
        majority = """SELECT DISTINCT ON ({c}) {c} AS child, {p} AS parent FROM mkt_uk.postcode
                      WHERE status='live' AND {c} IS NOT NULL AND {p} IS NOT NULL
                      GROUP BY {c}, {p} ORDER BY {c}, count(*) DESC"""
        for cl, pl, cc, pc in (("lsoa", "msoa", "lsoa21_code", "msoa21_code"),
                               ("msoa", "lad", "msoa21_code", "lad_code"),
                               ("lad", "region", "lad_code", "region_code")):
            ctx.sql(f"liên kết {cl} → {pl}", link.format(pairs=majority.format(c=cc, p=pc)),
                    {"rel": "best_fit", "w": 1, "basis": "address_count", "cl": cl, "pl": pl})
        if ctx.scalar("SELECT count(*) FROM core.geo_area_link") == 0:
            raise LoadError("Không tạo được liên kết cấp nào — kiểm tra ranh giới đã nạp chưa")
        ctx.drop_stage("onspd")
        return {"postcodes": n_pc}
