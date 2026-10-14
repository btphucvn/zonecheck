"""Đưa chỉ số gốc (LSOA/MSOA/OA) lên mọi cấp trang theo thành phần dân số (geo_area_link overlaps).

- Trung bình (rates, chỉ số, khoảng cách, điểm): Σ(w·pop·v) / Σ(w·pop) trên các LSOA có giá trị.
- Tổng (Census, council tax stock): Σ(w·v), w = phần LSOA nằm trong khu; value_json cộng theo từng nhóm.
- Chỉ số gốc MSOA (thu nhập): LSOA nhận giá trị MSOA cha trước khi tính.
- Không ghi đè giá trị gốc từ nguồn (release_id có giá trị); giá trị do rollup tạo trước đó được cập nhật.
- Bỏ khu có < 50% dân số có dữ liệu. ZC_METRICS="uk.zone.%" để chỉ tính lại một nhóm chỉ số.
"""
from __future__ import annotations

import logging

from ..loaders.base import LoadContext, LoadError
from .base import Step

log = logging.getLogger(__name__)

MEAN_PATTERNS = ["uk.iod25.%_score", "uk.wimd25.%_score", "uk.tcm.%", "uk.pcm.%", "uk.income.%", "uk.access.%",
                 "uk.schools.%", "uk.zone.%", "uk.bb.%", "uk.noise.%", "uk.climate.%", "uk.road.%", "uk.london.%",
                 "uk.benefit.%", "uk.own.%"]
SUM_PATTERNS = ["uk.census21.%", "uk.ctax.stock", "uk.pop.%"]
TARGETS = ["msoa", "lad", "region", "nation", "sector", "district", "postal_area", "town", "ward"]
MIN_COVERAGE = 0.5


class Rollup(Step):
    name = "rollup"
    depends_on = ("membership", "access")
    needs_sources = ("iod2025", "wimd", "census2021", "transport_connectivity", "defra_pcm", "ons_income_msoa")
    description = "Đưa chỉ số LSOA/MSOA lên sector, district, town, MSOA, LAD, region, nation (theo dân số)"

    def run(self, ctx: LoadContext) -> dict:
        def metrics(patterns):
            return [r[0] for r in ctx.conn.execute(
                "SELECT id FROM core.metric WHERE market_code='uk' AND id LIKE ANY(%s) ORDER BY id", (patterns,))]
        import os
        only = os.environ.get("ZC_METRICS")  # ví dụ "uk.zone.%" → chỉ tính lại nhóm chỉ số này
        mean_ids, sum_ids = metrics(MEAN_PATTERNS), metrics(SUM_PATTERNS)
        if only:
            mean_ids = [m for m in mean_ids if __import__("fnmatch").fnmatch(m, only.replace("%", "*"))]
            sum_ids = [m for m in sum_ids if __import__("fnmatch").fnmatch(m, only.replace("%", "*"))]
            log.info("    chỉ tính lại %s (ZC_METRICS)", only)
        ctx.conn.execute("""UPDATE core.metric SET aggregation='weighted_mean' WHERE id = ANY(%s) AND aggregation <> 'weighted_mean'""",
                         (mean_ids,))
        log.info("    %s chỉ số trung bình, %s chỉ số tổng", len(mean_ids), len(sum_ids))

        # giá trị LSOA nguồn (kỳ mới nhất từng chỉ số); chỉ số gốc MSOA → LSOA kế thừa từ MSOA cha
        ctx.sql("giá trị nguồn ở LSOA", """
            CREATE TEMP TABLE src ON COMMIT DROP AS
            WITH latest AS (SELECT metric_id, max(period) p FROM core.metric_value
                            WHERE market_code='uk' AND metric_id = ANY(%(ids)s) GROUP BY 1)
            SELECT v.area_id AS lsoa_id, v.metric_id, v.period, v.value_num, v.value_json
            FROM core.metric_value v JOIN latest l ON l.metric_id = v.metric_id AND l.p = v.period
            JOIN core.geo_area a ON a.id = v.area_id AND a.level_code = 'lsoa'
            WHERE v.market_code='uk' AND NOT v.is_suppressed
            UNION ALL
            SELECT k.child_id, v.metric_id, v.period, v.value_num, NULL
            FROM core.metric_value v JOIN latest l ON l.metric_id = v.metric_id AND l.p = v.period
            JOIN core.geo_area m ON m.id = v.area_id AND m.level_code = 'msoa'
            JOIN core.geo_area_link k ON k.parent_id = m.id AND k.relation = 'best_fit'
            JOIN core.geo_area c ON c.id = k.child_id AND c.level_code = 'lsoa'
            JOIN core.metric mt ON mt.id = v.metric_id AND mt.native_level = 'msoa'  -- chỉ chỉ số gốc MSOA (thu nhập)
            WHERE v.market_code='uk' AND NOT v.is_suppressed""",
                {"ids": mean_ids + sum_ids})
        ctx.conn.execute("CREATE INDEX ON src (lsoa_id)")
        ctx.conn.execute("ANALYZE src")
        ctx.sql("liên kết thành phần + dân số", """
            CREATE TEMP TABLE comp ON COMMIT DROP AS
            SELECT k.child_id AS lsoa_id, k.parent_id AS area_id, k.weight, k.weight * la.population AS wpop,
                   p.level_code, p.population AS area_pop
            FROM core.geo_area_link k JOIN core.geo_area la ON la.id = k.child_id
            JOIN core.geo_area p ON p.id = k.parent_id AND p.level_code = ANY(%s)
            WHERE k.relation = 'overlaps' AND k.weight_basis = 'population'""", (TARGETS,))
        ctx.conn.execute("CREATE INDEX ON comp (lsoa_id)")
        ctx.conn.execute("ANALYZE comp")

        n_mean = ctx.sql("trung bình theo dân số", f"""
            INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size)
            SELECT 'uk', c.area_id, s.metric_id, s.period, sum(s.value_num * c.wpop) / sum(c.wpop), count(*)
            FROM comp c JOIN src s ON s.lsoa_id = c.lsoa_id AND s.metric_id = ANY(%s) AND s.value_num IS NOT NULL
            GROUP BY c.area_id, s.metric_id, s.period
            HAVING sum(c.wpop) >= {MIN_COVERAGE} * max(c.area_pop)
            -- ghi đè giá trị do rollup tạo trước đó (release_id NULL), không đụng giá trị gốc từ nguồn
            ON CONFLICT (market_code, area_id, metric_id, period) DO UPDATE SET value_num = EXCLUDED.value_num,
                sample_size = EXCLUDED.sample_size, computed_at = now()
            WHERE core.metric_value.release_id IS NULL""", (mean_ids,))
        postal = "('sector', 'district', 'postal_area', 'town', 'ward')"
        ctx.sql("tổng phân bố (value_json) theo nhóm", f"""
            CREATE TEMP TABLE sum_json ON COMMIT DROP AS
            SELECT area_id, metric_id, period, jsonb_object_agg(k, round(t)) AS j
            FROM (SELECT c.area_id, s.metric_id, s.period, e.key AS k, sum(e.value::numeric * c.weight) AS t
                  FROM comp c JOIN src s ON s.lsoa_id = c.lsoa_id AND s.metric_id = ANY(%s)
                  CROSS JOIN LATERAL jsonb_each_text(coalesce(s.value_json, '{{}}'::jsonb)) e
                  WHERE c.level_code IN {postal} AND e.value ~ '^-?[0-9.]+$'
                  GROUP BY 1, 2, 3, 4) x
            GROUP BY 1, 2, 3""", (sum_ids,))
        n_sum = ctx.sql("tổng theo phần LSOA", f"""
            INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, value_json)
            SELECT 'uk', t.area_id, t.metric_id, t.period, t.v, j.j
            FROM (SELECT c.area_id, s.metric_id, s.period, round(sum(s.value_num * c.weight)::numeric) v
                  FROM comp c JOIN src s ON s.lsoa_id = c.lsoa_id AND s.metric_id = ANY(%s) AND s.value_num IS NOT NULL
                  WHERE c.level_code IN {postal} GROUP BY 1, 2, 3) t
            LEFT JOIN sum_json j USING (area_id, metric_id, period)
            ON CONFLICT (market_code, area_id, metric_id, period) DO UPDATE SET value_num = EXCLUDED.value_num,
                value_json = EXCLUDED.value_json, computed_at = now()
            WHERE core.metric_value.release_id IS NULL""", (sum_ids,))

        # ---- kiểm tra: độ phủ sector & khớp tổng dân số
        cov = dict(ctx.conn.execute("""
            SELECT v.metric_id, count(*) * 100.0 / (SELECT count(*) FROM core.geo_area WHERE level_code='sector'
                   AND is_active AND population > 0)
            FROM core.metric_value v JOIN core.geo_area a ON a.id = v.area_id AND a.level_code = 'sector'
            WHERE v.metric_id IN ('uk.tcm.overall', 'uk.pcm.no2', 'uk.access.gp_dist_m', 'uk.census21.ts001')
            GROUP BY 1""").fetchall())
        log.info("    %% sector (có dân) có giá trị: %s", {k: round(v, 1) for k, v in cov.items()})
        low = {k: v for k, v in cov.items() if v < 95}
        if low:
            raise LoadError(f"Độ phủ sector thấp: {low}")
        tot = ctx.scalar("""SELECT sum(v.value_num) FROM core.metric_value v JOIN core.geo_area a ON a.id = v.area_id
            WHERE v.metric_id = 'uk.census21.ts001' AND a.level_code = 'sector'""")
        log.info("    Σ dân số Census qua các sector: %s", f"{tot:,.0f}")
        if abs(tot - 59_597_542) > 59_597_542 * 0.002:
            raise LoadError(f"Tổng dân số qua sector ({tot:,.0f}) lệch Census E&W > 0,2%")
        return {"mean_values": n_mean, "sum_values": n_sum, "sector_coverage": cov}
