"""Chỉ số giá nhà từ HM Land Registry Price Paid (giao dịch chuẩn, category A) → mọi cấp khu.

Postcode của giao dịch xác định trực tiếp LSOA/MSOA/LAD/region/nation/sector/district/postal_area;
town = giao dịch có postcode trong bán kính town (giống bước membership). Trung vị tính lại từ giao dịch,
không suy từ trung vị cấp dưới. Ẩn khi < 5 giao dịch.
"""
from __future__ import annotations

import logging

from ..loaders.base import LoadContext, LoadError
from ..loaders.metrics import register_metric
from .base import Step
from .membership import TOWN_RADIUS_M

log = logging.getLogger(__name__)

TYPES = {"D": "detached", "S": "semi", "T": "terraced", "F": "flat"}
MIN_SAMPLE = 5
POSTCODE_LEVELS = {"lsoa": "p.lsoa21_code", "msoa": "p.msoa21_code", "lad": "p.lad_code", "region": "p.region_code",
                   "nation": "p.country_code", "sector": "p.sector", "district": "p.district",
                   "postal_area": "p.postal_area"}


class Housing(Step):
    name = "housing"
    depends_on = ("membership",)
    needs_sources = ("ppd", "onspd", "os_open_names")
    description = "Giá nhà: trung vị 24 tháng (chung + theo loại), số giao dịch, thay đổi 5 năm, trung vị theo năm"

    def run(self, ctx: LoadContext) -> dict:
        last = ctx.scalar("SELECT max(transfer_date) FROM mkt_uk.price_paid WHERE ppd_category = 'A'")
        start = ctx.scalar("SELECT (%s::date - interval '24 months')::date", (last,))
        y_last = last.year if last.month >= 12 else last.year - 1  # năm đầy đủ gần nhất
        log.info("    giao dịch tới %s; cửa sổ 24 tháng từ %s; chuỗi năm %s–%s", last, start, y_last - 9, y_last)

        # giao dịch × khu (một giao dịch thuộc nhiều cấp)
        union = " UNION ALL ".join(
            f"SELECT a.id area_id, t.price, t.property_type, t.transfer_date FROM tx t JOIN mkt_uk.postcode p "
            f"ON p.postcode = t.postcode JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='{lvl}' "
            f"AND a.code = {col}" for lvl, col in POSTCODE_LEVELS.items())
        ctx.sql("giao dịch 10 năm", """
            CREATE TEMP TABLE tx ON COMMIT DROP AS
            SELECT postcode, price, property_type, transfer_date FROM mkt_uk.price_paid
            WHERE ppd_category = 'A' AND property_type <> 'O' AND transfer_date >= make_date(%s, 1, 1)
              AND postcode IS NOT NULL""", (y_last - 9,))
        ctx.conn.execute("CREATE INDEX ON tx (postcode)")
        ctx.conn.execute("ANALYZE tx")
        radius = "CASE t.attrs->>'local_type' " + " ".join(f"WHEN '{k}' THEN {v}" for k, v in TOWN_RADIUS_M.items()) + " END"
        ctx.sql("giao dịch × khu", f"""
            CREATE TEMP TABLE tx_area ON COMMIT DROP AS
            {union}
            UNION ALL
            SELECT t.id, x.price, x.property_type, x.transfer_date
            FROM core.geo_area t
            JOIN mkt_uk.postcode p ON ST_DWithin(p.geom, t.centroid, ({radius}) / 55000.0)
                 AND ST_DWithin(p.geom::geography, t.centroid::geography, {radius}) AND p.status = 'live'
            JOIN tx x ON x.postcode = p.postcode
            WHERE t.market_code='uk' AND t.level_code='town' AND t.is_active""")
        ctx.conn.execute("ANALYZE tx_area")

        ctx.sql("trung vị theo khu", f"""
            CREATE TEMP TABLE price_stats ON COMMIT DROP AS
            SELECT area_id,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY price) FILTER (WHERE transfer_date > %(s)s) AS median,
                   count(*) FILTER (WHERE transfer_date > %(s)s) AS n,
                   {", ".join(f"percentile_cont(0.5) WITHIN GROUP (ORDER BY price) FILTER (WHERE transfer_date > %(s)s AND property_type = '{c}') AS median_{k}, count(*) FILTER (WHERE transfer_date > %(s)s AND property_type = '{c}') AS n_{k}" for c, k in TYPES.items())},
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY price) FILTER (WHERE transfer_date > %(l12)s) AS median_12m,
                   count(*) FILTER (WHERE transfer_date > %(l12)s) AS n_12m,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY price) FILTER (WHERE transfer_date > %(b12)s AND transfer_date <= %(b0)s) AS median_5y_ago,
                   count(*) FILTER (WHERE transfer_date > %(b12)s AND transfer_date <= %(b0)s) AS n_5y_ago
            FROM tx_area GROUP BY area_id""",
                {"s": start, "l12": ctx.scalar("SELECT (%s::date - interval '12 months')::date", (last,)),
                 "b0": ctx.scalar("SELECT (%s::date - interval '60 months')::date", (last,)),
                 "b12": ctx.scalar("SELECT (%s::date - interval '72 months')::date", (last,))})
        ctx.sql("trung vị theo năm", """
            CREATE TEMP TABLE price_years ON COMMIT DROP AS
            SELECT area_id, jsonb_object_agg(y, jsonb_build_object('median', round(m::numeric), 'n', n)) AS series
            FROM (SELECT area_id, extract(year FROM transfer_date)::int y,
                         percentile_cont(0.5) WITHIN GROUP (ORDER BY price) m, count(*) n
                  FROM tx_area WHERE transfer_date < make_date(%s + 1, 1, 1) GROUP BY 1, 2 HAVING count(*) >= %s) x
            GROUP BY area_id""", (y_last, MIN_SAMPLE))

        # ---- đăng ký chỉ số
        common = dict(category="housing", dataset="uk.land_registry.ppd", period_type="rolling_12m",
                      native_level="postcode_unit", aggregation="median_recompute", scope="uk.ew")
        register_metric(ctx, "uk.price.median", value_type="currency", unit="GBP", direction=-1,
                        name="Median sale price (last 24 months)", **common)
        for k in TYPES.values():
            register_metric(ctx, f"uk.price.median_{k}", value_type="currency", unit="GBP", direction=-1,
                            name=f"Median sale price: {k} (last 24 months)", scorable=False, **common)
        register_metric(ctx, "uk.price.sales", value_type="count", name="Number of sales (last 24 months)",
                        scorable=False, **{**common, "aggregation": "sum"})
        register_metric(ctx, "uk.price.change_5y_pct", value_type="percent", unit="%", decimals=0,
                        name="Median price change over 5 years", scorable=False, **common)
        register_metric(ctx, "uk.price.median_by_year", value_type="distribution",
                        name="Median sale price by year (10 years)", scorable=False, **{**common, "period_type": "year"})
        ids = ["uk.price.median", "uk.price.sales", "uk.price.change_5y_pct", "uk.price.median_by_year"] + \
              [f"uk.price.median_{k}" for k in TYPES.values()]
        ctx.sql("xoá giá trị kỳ này", "DELETE FROM core.metric_value WHERE market_code='uk' AND metric_id = ANY(%s) AND period = %s",
                (ids, last))
        vals = [("uk.price.median", "s.median", "s.n")] + \
               [(f"uk.price.median_{k}", f"s.median_{k}", f"s.n_{k}") for k in TYPES.values()]
        lateral = ", ".join(f"('{m}', {v}, {n})" for m, v, n in vals)
        n1 = ctx.sql("ghi trung vị", f"""
            INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size,
                                           is_suppressed, suppression_reason)
            SELECT 'uk', s.area_id, m.metric_id, %s,
                   CASE WHEN m.n >= {MIN_SAMPLE} THEN round(m.v::numeric) END, m.n,
                   m.n < {MIN_SAMPLE}, CASE WHEN m.n < {MIN_SAMPLE} THEN 'small_sample' END
            FROM price_stats s CROSS JOIN LATERAL (VALUES {lateral}) m(metric_id, v, n)
            WHERE m.n > 0""", (last,))
        n2 = ctx.sql("ghi số giao dịch + thay đổi 5 năm", f"""
            INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size)
            SELECT 'uk', area_id, 'uk.price.sales', %s, n, n FROM price_stats
            UNION ALL
            SELECT 'uk', area_id, 'uk.price.change_5y_pct', %s,
                   round(((median_12m - median_5y_ago) * 100.0 / median_5y_ago)::numeric, 1), n_12m
            FROM price_stats WHERE n_12m >= 10 AND n_5y_ago >= 10""", (last, last))
        n3 = ctx.sql("ghi chuỗi theo năm", """
            INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_json)
            SELECT 'uk', area_id, 'uk.price.median_by_year', %s, series FROM price_years""", (last,))

        # ---- kiểm tra hợp lý
        def nat(metric, code):
            return ctx.scalar("""SELECT v.value_num FROM core.metric_value v JOIN core.geo_area a ON a.id = v.area_id
                WHERE v.metric_id = %s AND v.period = %s AND a.code = %s AND a.level_code IN ('nation','region')""",
                              (metric, last, code))
        eng, wal, lon = nat("uk.price.median", "E92000001"), nat("uk.price.median", "W92000004"), nat("uk.price.median", "E12000007")
        det, flat = nat("uk.price.median_detached", "E92000001"), nat("uk.price.median_flat", "E92000001")
        log.info("    trung vị 24 tháng: England £%s, Wales £%s, London £%s; England detached £%s vs flat £%s",
                 f"{eng:,.0f}", f"{wal:,.0f}", f"{lon:,.0f}", f"{det:,.0f}", f"{flat:,.0f}")
        if not (220_000 <= eng <= 380_000 and 150_000 <= wal <= 300_000 and lon > eng and det > flat):
            raise LoadError(f"Giá trung vị bất thường: England {eng}, Wales {wal}, London {lon}, detached {det}, flat {flat}")
        ctx.check_range("trung vị mọi khu", "core.metric_value v", "v.value_num", 10_000, 20_000_000,
                        where=f"v.metric_id = 'uk.price.median' AND v.period = '{last}'")
        supp = ctx.scalar("""SELECT count(*) FILTER (WHERE is_suppressed) * 100.0 / count(*) FROM core.metric_value v
            JOIN core.geo_area a ON a.id = v.area_id WHERE v.metric_id='uk.price.median' AND v.period=%s
            AND a.level_code='sector'""", (last,))
        log.info("    sector bị ẩn do < %s giao dịch: %.1f%%", MIN_SAMPLE, supp)
        return {"period_end": str(last), "values": n1 + n2 + n3}
