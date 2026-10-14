"""UK Output Area Classification 2021/22 → mkt_uk.oac (OA → supergroup/group/subgroup) + mkt_uk.oac_label."""
from __future__ import annotations

import json
import logging

from .base import LoadContext, LoadError, Loader

log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.oac (
    oa21_code text PRIMARY KEY,
    supergroup text NOT NULL,
    grp text NOT NULL,
    subgroup text NOT NULL,
    release_id bigint REFERENCES ops.dataset_release (id)
);
CREATE INDEX IF NOT EXISTS oac_grp_idx ON mkt_uk.oac (grp);
CREATE TABLE IF NOT EXISTS mkt_uk.oac_label (
    level text NOT NULL,           -- supergroup | group
    code text NOT NULL,
    name text NOT NULL,
    pen_portrait text,
    release_id bigint REFERENCES ops.dataset_release (id),
    PRIMARY KEY (level, code)
);
COMMENT ON TABLE mkt_uk.oac IS 'UK Output Area Classification 2021/22 (GeoDS/ONS, OGL v3): nhóm của mỗi OA 2021 (E&W).';
COMMENT ON TABLE mkt_uk.oac_label IS 'Tên và mô tả (pen portrait) của supergroup/group OAC 2021/22, từ GeoDS.'"""


class OacLoader(Loader):
    source = "geods_oac"
    depends_on = ("boundaries_oa21",)
    description = "OAC 2021/22 → mkt_uk.oac + mkt_uk.oac_label"

    def load(self, ctx: LoadContext) -> dict:
        import pyarrow.parquet as pq
        rows = [(r["Geography_Code"], str(r["Supergroup"]), str(r["Group"]), str(r["Subgroup"]))
                for r in pq.read_table(ctx.file(r"UK_OAC_Final\.parquet$")).to_pylist()
                if str(r["Geography_Code"])[:1] in ("E", "W")]
        labels = json.loads(ctx.file(r"oac_labels\.json$").read_text())
        ctx.conn.execute(DDL)
        bad = [r for r in rows if not (r[2].startswith(r[1]) and r[3].startswith(r[2]))]
        if bad:
            raise LoadError(f"{len(bad)} OA có group/subgroup không thuộc supergroup cha, ví dụ {bad[:3]}")
        groups = {r[2] for r in rows}
        missing = groups - set(labels["groups"])
        if missing:
            raise LoadError(f"Group không có nhãn: {sorted(missing)}")
        st = ctx.stage_table("oac", ["oa", "sg", "g", "sub"])
        ctx.copy_rows(st, ["oa", "sg", "g", "sub"], rows, "COPY OAC")
        match = ctx.scalar(f"""SELECT avg((a.id IS NOT NULL)::int)::float8 FROM {st} s
            LEFT JOIN core.geo_area a ON a.market_code = 'uk' AND a.level_code = 'oa' AND a.code = s.oa""")
        n_oa = ctx.scalar("SELECT count(*) FROM core.geo_area WHERE market_code='uk' AND level_code='oa' AND is_active")
        log.info("    %s OA E&W, %.2f%% khớp ranh giới OA 2021 (%s OA đang dùng)", f"{len(rows):,}", match * 100, f"{n_oa:,}")
        if match < 0.99 or abs(len(rows) - n_oa) > 0.01 * n_oa:
            raise LoadError(f"OAC không khớp OA 2021: khớp {match:.2%}, {len(rows)} so với {n_oa}")
        ctx.sql("thay mkt_uk.oac", "DELETE FROM mkt_uk.oac")
        ctx.sql("ghi mkt_uk.oac", f"INSERT INTO mkt_uk.oac SELECT oa, sg, g, sub, %s FROM {st}", (ctx.release_id,))
        ctx.sql("thay nhãn", "DELETE FROM mkt_uk.oac_label")
        lab = [("supergroup", k, v["name"], v["pen_portrait"], ctx.release_id) for k, v in labels["supergroups"].items()] + \
              [("group", k, v["name"], v["pen_portrait"], ctx.release_id) for k, v in labels["groups"].items()]
        ctx.copy_rows("mkt_uk.oac_label", ["level", "code", "name", "pen_portrait", "release_id"], lab, "COPY nhãn OAC")
        ctx.drop_stage("oac")
        return {"oa": len(rows), "groups": len(groups), "labels": len(lab), "oa_match": round(match, 4)}
