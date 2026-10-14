"""Phân vị chỉ số (theo cấp + phạm vi so sánh) và điểm khu theo mô hình uk.v1 (PLAN §3.5).

1. percentile (0–100, cao = giá trị lớn) cho kỳ mới nhất mỗi chỉ số, trong (chỉ số, cấp, phạm vi):
   uk.england → chỉ khu England; uk.wales → chỉ Wales; uk.ew → E+W; uk.uk → tất cả.
2. Điểm nhóm = Σ w·p' / Σ w trên thành phần có dữ liệu, p' = percentile (hoặc 100 − percentile nếu direction = −1).
   coverage = Σ w có dữ liệu / Σ w. Nhóm có coverage < 0,5 → NULL.
3. Điểm tổng theo vai trò = Σ wᵥ·điểm nhóm / Σ wᵥ trên các nhóm có điểm; điểm mạnh/yếu = nhóm ≥ 70 / ≤ 30.
Dân tộc, tôn giáo không được dùng (metric sensitive không is_scorable).
"""
from __future__ import annotations

import json
import logging

from ..loaders.base import LoadContext, LoadError
from .base import Step

log = logging.getLogger(__name__)

MODEL = "uk.v1"
LEVELS = ["lsoa", "msoa", "sector", "district", "postal_area", "town", "ward", "lad", "region"]
CATEGORIES = {
    "affordability": ("Affordability", {"uk.price.median": 2, "uk.ctax.band_d": 0.5}),
    "safety": ("Safety", {"uk.crime.total_rate": 2, "uk.crime.violent_rate": 1, "uk.crime.burglary_rate": 1,
                          "uk.crime.asb_rate": 1}),
    "schools": ("Schools", {"uk.schools.primary_quality": 1, "uk.schools.secondary_quality": 1,
                            "uk.access.primary_dist_m": 0.5, "uk.access.secondary_dist_m": 0.5}),
    "transport": ("Transport", {"uk.tcm.overall": 2, "uk.access.rail_dist_m": 1, "uk.access.bus_stops_500m": 1}),
    "amenities": ("Amenities & health", {"uk.access.gp_dist_m": 1, "uk.access.supermarket_dist_m": 1,
                                         "uk.access.pharmacy_dist_m": 0.5, "uk.access.park_dist_m": 1,
                                         "uk.access.food_1km": 0.5}),
    "environment": ("Environment & risk", {"uk.pcm.no2": 1, "uk.pcm.pm25": 1, "uk.zone.flood_zone3_share": 1,
                                          "uk.zone.sw_high_share": 1}),
    "connectivity": ("Broadband & mobile", {"uk.bb.gigabit_pct": 2, "uk.bb.sfbb_pct": 1, "uk.bb.no_decent_pct": 1}),
    "economy": ("Income & deprivation", {"uk.income.net": 1, "uk.iod25.imd_score": 1, "uk.wimd25.overall_score": 1}),
}
PERSONAS = {  # vai trò → trọng số nhóm
    "buyer": ("First-time buyer", {"affordability": 3, "safety": 2, "schools": 1, "transport": 2, "amenities": 1,
                                   "environment": 2, "connectivity": 1, "economy": 1}),
    "renter": ("Renter", {"affordability": 3, "safety": 2, "schools": 0.5, "transport": 3, "amenities": 2,
                          "environment": 1, "connectivity": 2, "economy": 1}),
    "family": ("Family", {"affordability": 2, "safety": 3, "schools": 3, "transport": 1, "amenities": 2,
                          "environment": 2, "connectivity": 1, "economy": 1}),
    "commuter": ("Commuter", {"affordability": 2, "safety": 1, "schools": 0.5, "transport": 4, "amenities": 1,
                              "environment": 1, "connectivity": 2, "economy": 1}),
    "retiree": ("Retiree", {"affordability": 2, "safety": 3, "schools": 0, "transport": 1, "amenities": 3,
                            "environment": 3, "connectivity": 1, "economy": 1}),
    "newcomer": ("New to the UK", {"affordability": 3, "safety": 2, "schools": 1, "transport": 3, "amenities": 2,
                                   "environment": 1, "connectivity": 2, "economy": 1}),
}
SANITY = [  # (nhóm, mã khu thấp hơn, mã khu cao hơn, mô tả)
    ("safety", "E09000033", "E06000017", "Westminster kém an toàn hơn Rutland"),
    ("affordability", "E09000020", "E06000009", "Kensington & Chelsea kém phải chăng hơn Blackpool"),
    ("transport", "E06000052", "E09000019", "Cornwall có giao thông kém hơn Islington"),
]


class Scoring(Step):
    name = "scoring"
    depends_on = ("percentiles",)
    description = "Điểm 8 nhóm × 6 vai trò (mô hình uk.v1) từ phân vị đã tính"

    def run(self, ctx: LoadContext) -> dict:
        # ---------- 2. danh mục mô hình
        ctx.conn.execute("""INSERT INTO core.score_model (id, market_code, version, description, params, is_active)
            VALUES (%s, 'uk', 1, 'Mô hình đầu tiên: phân vị trong phạm vi so sánh, trung bình có trọng số', %s, false)
            ON CONFLICT (id) DO UPDATE SET params = EXCLUDED.params""",
                         (MODEL, json.dumps({"min_category_coverage": 0.5})))
        ctx.conn.execute("DELETE FROM core.score_component WHERE model_id = %s", (MODEL,))
        ctx.conn.execute("DELETE FROM core.persona_weight WHERE model_id = %s", (MODEL,))
        for i, (code, (name, comps)) in enumerate(CATEGORIES.items()):
            ctx.conn.execute("""INSERT INTO core.score_category (code, name_i18n, sort_order) VALUES (%s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET name_i18n = EXCLUDED.name_i18n, sort_order = EXCLUDED.sort_order""",
                             (code, json.dumps({"en": name}), i))
            for mid, w in comps.items():
                ok = ctx.scalar("SELECT is_scorable FROM core.metric WHERE id = %s", (mid,))
                if ok is None:
                    raise LoadError(f"Thành phần {mid} chưa có trong core.metric")
                if not ok:
                    raise LoadError(f"Thành phần {mid} không is_scorable (nhạy cảm?) — không được dùng tính điểm")
                ctx.conn.execute("INSERT INTO core.score_component (model_id, category_code, metric_id, weight) VALUES (%s,%s,%s,%s)",
                                 (MODEL, code, mid, w))
        for i, (code, (name, weights)) in enumerate(PERSONAS.items()):
            ctx.conn.execute("""INSERT INTO core.persona (code, name_i18n, sort_order) VALUES (%s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET name_i18n = EXCLUDED.name_i18n, sort_order = EXCLUDED.sort_order""",
                             (code, json.dumps({"en": name}), i))
            for cat, w in weights.items():
                ctx.conn.execute("INSERT INTO core.persona_weight (model_id, persona_code, category_code, weight) VALUES (%s,%s,%s,%s)",
                                 (MODEL, code, cat, w))

        # ---------- 3. điểm nhóm
        ctx.sql("xoá điểm cũ", "DELETE FROM core.area_category_score WHERE model_id = %s", (MODEL,))
        ctx.sql("điểm nhóm", """
            WITH latest AS (SELECT metric_id, max(period) p FROM core.metric_value WHERE market_code='uk' GROUP BY 1),
            comp AS (SELECT c.category_code, c.metric_id, c.weight, m.direction,
                            sum(c.weight) OVER (PARTITION BY c.category_code) AS w_all
                     FROM core.score_component c JOIN core.metric m ON m.id = c.metric_id WHERE c.model_id = %(m)s),
            s AS (
                SELECT v.area_id, c.category_code,
                       sum(c.weight * CASE WHEN c.direction < 0 THEN 100 - v.percentile ELSE v.percentile END) / sum(c.weight) AS score,
                       sum(c.weight) / max(c.w_all) AS coverage
                FROM comp c JOIN latest l ON l.metric_id = c.metric_id
                JOIN core.metric_value v ON v.market_code='uk' AND v.metric_id = c.metric_id AND v.period = l.p
                     AND v.percentile IS NOT NULL
                JOIN core.geo_area a ON a.id = v.area_id AND a.level_code = ANY(%(lv)s)
                GROUP BY v.area_id, c.category_code)
            INSERT INTO core.area_category_score (model_id, area_id, category_code, score, coverage)
            SELECT %(m)s, area_id, category_code, CASE WHEN coverage >= 0.5 THEN round(score::numeric, 1) END,
                   least(coverage, 1) FROM s""", {"m": MODEL, "lv": LEVELS})
        ctx.sql("phân vị điểm nhóm (theo cấp)", """
            UPDATE core.area_category_score s SET percentile = round(x.p::numeric, 1)
            FROM (SELECT s2.area_id, s2.category_code, 100 * percent_rank() OVER
                         (PARTITION BY a.level_code, s2.category_code ORDER BY s2.score) p
                  FROM core.area_category_score s2 JOIN core.geo_area a ON a.id = s2.area_id
                  WHERE s2.model_id = %s AND s2.score IS NOT NULL) x
            WHERE s.model_id = %s AND s.area_id = x.area_id AND s.category_code = x.category_code""", (MODEL, MODEL))

        # ---------- 4. điểm tổng theo vai trò
        ctx.sql("xoá điểm tổng cũ", "DELETE FROM core.area_overall_score WHERE model_id = %s", (MODEL,))
        ctx.sql("điểm tổng theo vai trò", """
            WITH pw AS (SELECT persona_code, category_code, weight, sum(weight) OVER (PARTITION BY persona_code) w_all
                        FROM core.persona_weight WHERE model_id = %(m)s AND weight > 0),
            o AS (SELECT s.area_id, pw.persona_code, sum(pw.weight * s.score) / sum(pw.weight) score,
                         sum(pw.weight) / max(pw.w_all) coverage
                  FROM core.area_category_score s JOIN pw ON pw.category_code = s.category_code
                  WHERE s.model_id = %(m)s AND s.score IS NOT NULL GROUP BY 1, 2),
            sw AS (SELECT area_id,
                          (array_agg(category_code ORDER BY score DESC) FILTER (WHERE score >= 70))[1:3] strengths,
                          (array_agg(category_code ORDER BY score ASC) FILTER (WHERE score <= 30))[1:3] weaknesses
                   FROM core.area_category_score WHERE model_id = %(m)s AND score IS NOT NULL GROUP BY 1)
            INSERT INTO core.area_overall_score (model_id, area_id, persona_code, score, coverage, strengths, weaknesses)
            SELECT %(m)s, o.area_id, o.persona_code, round(o.score::numeric, 1), least(o.coverage, 1), sw.strengths, sw.weaknesses
            FROM o LEFT JOIN sw USING (area_id)""", {"m": MODEL})
        ctx.sql("phân vị điểm tổng", """
            UPDATE core.area_overall_score s SET percentile = round(x.p::numeric, 1)
            FROM (SELECT s2.area_id, s2.persona_code, 100 * percent_rank() OVER
                         (PARTITION BY a.level_code, s2.persona_code ORDER BY s2.score) p
                  FROM core.area_overall_score s2 JOIN core.geo_area a ON a.id = s2.area_id WHERE s2.model_id = %s) x
            WHERE s.model_id = %s AND s.area_id = x.area_id AND s.persona_code = x.persona_code""", (MODEL, MODEL))

        # ---------- 5. kiểm tra hợp lý
        dist = ctx.conn.execute("""SELECT a.level_code, s.category_code, count(*), round(avg(s.score)::numeric, 1),
                round(stddev(s.score)::numeric, 1), round(avg(s.coverage)::numeric, 2)
            FROM core.area_category_score s JOIN core.geo_area a ON a.id = s.area_id
            WHERE s.model_id = %s AND a.level_code IN ('sector', 'lad') GROUP BY 1, 2 ORDER BY 1, 2""", (MODEL,)).fetchall()
        for r in dist:
            log.info("    %-7s %-13s n=%-6s TB=%-5s độ lệch=%-5s phủ=%s", *r)
            if r[3] is not None and not 25 <= float(r[3]) <= 75:
                raise LoadError(f"Điểm trung bình {r[0]}/{r[1]} = {r[3]} lệch xa 50 — kiểm tra hướng/phân vị")
        for cat, low, high, desc in SANITY:
            lo, hi = (ctx.scalar("""SELECT s.score FROM core.area_category_score s JOIN core.geo_area a ON a.id = s.area_id
                WHERE s.model_id = %s AND s.category_code = %s AND a.level_code = 'lad' AND a.code = %s""", (MODEL, cat, c))
                      for c in (low, high))
            log.info("    kiểm tra định hướng: %s → %s vs %s", desc, lo, hi)
            if lo is None or hi is None or lo >= hi:
                raise LoadError(f"Kiểm tra định hướng thất bại: {desc} ({lo} vs {hi})")
        ctx.conn.execute("UPDATE core.score_model SET is_active = (id = %s) WHERE market_code = 'uk'", (MODEL,))
        n_cat = ctx.scalar("SELECT count(*) FROM core.area_category_score WHERE model_id = %s", (MODEL,))
        n_all = ctx.scalar("SELECT count(*) FROM core.area_overall_score WHERE model_id = %s", (MODEL,))
        return {"category_scores": n_cat, "overall_scores": n_all}


class Percentiles(Step):
    """Tách riêng vì nặng (~1 giờ, cập nhật ~7 triệu dòng): chỉ chạy lại khi dữ liệu chỉ số đổi."""
    name = "percentiles"
    depends_on = ("rollup", "crime", "housing")
    description = "Phân vị (0–100) kỳ mới nhất mỗi chỉ số, theo cấp + phạm vi so sánh (England / Wales / E&W / UK)"

    def run(self, ctx: LoadContext) -> dict:
        # ---------- 1. nation của từng khu (để xác định phạm vi so sánh)
        ctx.sql("nation của từng khu", """
            CREATE TEMP TABLE area_nation ON COMMIT DROP AS
            SELECT id AS area_id, left(code, 1) AS nat FROM core.geo_area
            WHERE market_code='uk' AND level_code IN ('lsoa','msoa','lad','region','nation') AND left(code, 1) IN ('E','W','S','N')
            UNION ALL
            SELECT parent_id, nat FROM (
                SELECT DISTINCT ON (k.parent_id) k.parent_id, left(c.code, 1) AS nat
                FROM core.geo_area_link k JOIN core.geo_area c ON c.id = k.child_id AND c.level_code = 'lsoa'
                JOIN core.geo_area p ON p.id = k.parent_id AND p.level_code IN ('sector','district','postal_area','town','ward')
                WHERE k.relation = 'overlaps'
                GROUP BY k.parent_id, left(c.code, 1)
                ORDER BY k.parent_id, sum(k.weight * c.population) DESC) x""")
        ctx.conn.execute("CREATE INDEX ON area_nation (area_id)")
        ctx.sql("phân vị (kỳ mới nhất, theo cấp + phạm vi)", """
            WITH latest AS (SELECT metric_id, max(period) p FROM core.metric_value WHERE market_code='uk'
                            AND metric_id LIKE %s GROUP BY 1),
            r AS (
                SELECT v.area_id, v.metric_id, v.period,
                       100 * percent_rank() OVER (
                           PARTITION BY v.metric_id, a.level_code,
                                        CASE WHEN m.comparable_scope_id IN ('uk.ew', 'uk.uk') THEN 'X' ELSE n.nat END
                           ORDER BY v.value_num) AS pct
                FROM core.metric_value v
                JOIN latest l ON l.metric_id = v.metric_id AND l.p = v.period
                JOIN core.metric m ON m.id = v.metric_id AND m.value_type NOT IN ('distribution', 'category')
                JOIN core.geo_area a ON a.id = v.area_id AND a.level_code = ANY(%s)
                JOIN area_nation n ON n.area_id = v.area_id
                WHERE v.market_code='uk' AND v.value_num IS NOT NULL AND NOT v.is_suppressed
                  AND (m.comparable_scope_id IS NULL OR m.comparable_scope_id = 'uk.uk'
                       OR (m.comparable_scope_id = 'uk.ew' AND n.nat IN ('E','W'))
                       OR (m.comparable_scope_id = 'uk.england' AND n.nat = 'E')
                       OR (m.comparable_scope_id = 'uk.wales' AND n.nat = 'W')))
            UPDATE core.metric_value v SET percentile = round(r.pct::numeric, 2)
            FROM r WHERE v.market_code='uk' AND v.area_id = r.area_id AND v.metric_id = r.metric_id AND v.period = r.period""",
                (__import__("os").environ.get("ZC_METRICS", "%"), LEVELS))

        n = ctx.scalar("""SELECT count(*) FROM core.metric_value v
            JOIN (SELECT metric_id, max(period) p FROM core.metric_value WHERE market_code='uk' GROUP BY 1) l
              ON l.metric_id = v.metric_id AND l.p = v.period
            WHERE v.market_code='uk' AND v.percentile IS NOT NULL""")
        ctx.sql("làm mới core.metric_latest", "REFRESH MATERIALIZED VIEW core.metric_latest")
        return {"values_with_percentile": n}
