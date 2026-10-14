"""OS Open Roads → mkt_uk.road: đoạn Motorway, A road, B road (GB) để tra đường lớn gần nhất một điểm (KNN, GiST)."""
from __future__ import annotations

import logging
import re
import zipfile

from .base import STAGE, LoadContext, LoadError, Loader

log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.road (
    id bigserial PRIMARY KEY,
    road_class text NOT NULL,          -- Motorway | A Road | B Road
    road_number text,                  -- M25, A205…
    name text,
    form_of_way text,                  -- Dual Carriageway, Single Carriageway, Roundabout, Slip Road…
    geom geometry(MultiLineString, 4326) NOT NULL,
    release_id bigint REFERENCES ops.dataset_release (id)
);
CREATE INDEX IF NOT EXISTS road_geom_idx ON mkt_uk.road USING gist (geom);
COMMENT ON TABLE mkt_uk.road IS 'OS Open Roads (OGL): đoạn đường Motorway / A / B ở GB, dùng tra đường lớn gần nhất một địa chỉ.'"""
CLASSES = ("Motorway", "A Road", "B Road")


class OpenRoadsLoader(Loader):
    source = "os_open_roads"
    description = "OS Open Roads → mkt_uk.road (Motorway, A, B)"

    def load(self, ctx: LoadContext) -> dict:
        z = ctx.file(r"\.zip$")
        with zipfile.ZipFile(z) as zf:
            gpkg = [n for n in zf.namelist() if n.lower().endswith(".gpkg")]
            if len(gpkg) != 1:
                raise LoadError(f"Cần 1 GeoPackage trong {z.name}, thấy {gpkg}")
            out = ctx.dir / "open_roads.gpkg"
            if not out.exists():
                with zf.open(gpkg[0]) as src, open(out, "wb") as dst:
                    while chunk := src.read(1 << 22):
                        dst.write(chunk)
        ctx.ogr_load(str(out), "roads", layer="road_link")
        cols = [r[0] for r in ctx.conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name='roads'", (STAGE,))]
        pick = lambda *pats: next((c for p in pats for c in cols if re.fullmatch(p, c)), None)  # noqa: E731
        c_class = pick(r"road_?classification", r"class")
        c_num = pick(r"road_?classification_?number", r"road_?number", r"roadnumber")
        c_name = pick(r"name_?1", r"name1", r"name")
        c_form = pick(r"form_?of_?way", r"formofway")
        if not c_class:
            raise LoadError(f"Không thấy cột phân loại đường trong road_link: {cols}")
        log.info("    cột: class=%s, number=%s, name=%s, form=%s", c_class, c_num, c_name, c_form)
        counts = dict(ctx.conn.execute(f"SELECT {c_class}, count(*) FROM {STAGE}.roads GROUP BY 1").fetchall())
        log.info("    phân loại: %s", counts)
        missing = [c for c in CLASSES if not counts.get(c)]
        if missing:
            raise LoadError(f"Thiếu loại đường {missing} trong {counts}")
        ctx.conn.execute(DDL)
        ctx.sql("thay mkt_uk.road", "TRUNCATE mkt_uk.road")
        n = ctx.sql("ghi đường lớn", f"""
            INSERT INTO mkt_uk.road (road_class, road_number, name, form_of_way, geom, release_id)
            SELECT {c_class}, {c_num or 'NULL'}, {c_name or 'NULL'}, {c_form or 'NULL'}, ST_Multi(geom), %s
            FROM {STAGE}.roads WHERE {c_class} = ANY(%s) AND geom IS NOT NULL""", (ctx.release_id, list(CLASSES)))
        km = ctx.scalar("""SELECT round(sum(ST_Length(geom::geography)) / 1000) FROM mkt_uk.road
                           WHERE road_class = 'Motorway' AND coalesce(form_of_way, '') NOT ILIKE '%%slip%%'""")
        log.info("    motorway (không tính slip road): %s km (GB ~3.700–4.300 km, dual carriageway có thể vẽ 2 tuyến)", km)
        if not 3000 <= (km or 0) <= 5500:
            raise LoadError(f"Tổng chiều dài motorway bất thường: {km} km")
        ctx.conn.execute("ANALYZE mkt_uk.road")
        ctx.drop_stage("roads")
        out.unlink(missing_ok=True)
        return {"segments": n, "motorway_km": km, "classes": counts}
