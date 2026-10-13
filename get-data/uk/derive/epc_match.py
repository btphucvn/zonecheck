"""Ghép giao dịch Price Paid ↔ chứng chỉ EPC theo địa chỉ → mkt_uk.ppd_epc_match, rồi tính £/m² theo khu.

Price Paid không có UPRN nên ghép bằng địa chỉ trong cùng postcode:
  Luật 1: chữ ký số (mọi token số như 12, 12A, B905 trong SAON + PAON) trùng chữ ký số của địa chỉ EPC,
          và từ đầu tiên của tên đường xuất hiện trong địa chỉ EPC. Nhà không có số: word_similarity ≥ 0,8.
  Luật 2 (chỉ cho giao dịch chưa ghép được): EPC hay bỏ số toà nhà ("APARTMENT 35 SALISBURY HOUSE" so với
          "APARTMENT 35 SALISBURY HOUSE 5 PALMER ROAD") → chữ ký số của SAON trùng chữ ký EPC VÀ tên toà nhà
          (phần chữ của SAON+PAON, ≥ 4 ký tự) nằm trong địa chỉ EPC.
Ứng viên thuộc > 1 UPRN → mơ hồ, bỏ. Chọn chứng chỉ gần ngày giao dịch nhất, ưu tiên chứng chỉ lập trước
(hoặc trong 180 ngày sau) ngày giao dịch. Kiểm tra: tỉ lệ ghép, diện tích theo loại nhà, £/m² England/London.
"""
from __future__ import annotations

import logging

from ..loaders.base import LoadContext, LoadError
from ..loaders.metrics import register_metric
from .base import Step
from .housing import MIN_SAMPLE, POSTCODE_LEVELS
from .membership import TOWN_RADIUS_M

log = logging.getLogger(__name__)

NUM_TOKEN = r"\m([A-Z]?[0-9]+[A-Z]?)\M"
GENERIC = r"\m(FLAT|APARTMENT|APT|UNIT|MAISONETTE)\M"
PPSQM_RANGE = (300, 60_000)  # £/m² ngoài khoảng này coi là lỗi dữ liệu (diện tích/giá sai), không tính trung vị


def _norm(expr: str) -> str:
    return f"trim(regexp_replace(upper(coalesce({expr}, '')), '[^A-Z0-9]+', ' ', 'g'))"


def _sig(expr: str) -> str:
    return f"coalesce((SELECT string_agg(m[1], ' ') FROM regexp_matches({expr}, '{NUM_TOKEN}', 'g') m), '')"


class EpcMatch(Step):
    name = "epc_match"
    depends_on = ("membership",)
    needs_sources = ("ppd", "epc", "onspd", "os_open_names")
    description = "Ghép Price Paid ↔ EPC theo địa chỉ → ppd_epc_match; trung vị £/m² và diện tích 24 tháng theo khu"

    def run(self, ctx: LoadContext) -> dict:
        ctx.sql("PPD chuẩn hoá", f"""
            CREATE TEMP TABLE p ON COMMIT DROP AS
            SELECT transaction_id, postcode, transfer_date, n, {_sig('sp')} AS sig, {_sig('ss')} AS sig_saon,
                   split_part({_norm('street')}, ' ', 1) AS sw,
                   trim(regexp_replace(sp, '{GENERIC}', '', 'g')) AS nm,
                   trim(regexp_replace(regexp_replace(regexp_replace(sp, '{GENERIC}', '', 'g'), '{NUM_TOKEN}', '', 'g'),
                                       ' +', ' ', 'g')) AS bname
            FROM (SELECT transaction_id, postcode, transfer_date, {_norm("concat_ws(' ', saon, paon)")} AS sp,
                         {_norm('saon')} AS ss, street, {_norm("concat_ws(' ', saon, paon, street)")} AS n
                  FROM mkt_uk.price_paid WHERE postcode IS NOT NULL) x""")
        ctx.sql("EPC chuẩn hoá", f"""
            CREATE TEMP TABLE e ON COMMIT DROP AS
            SELECT lmk_key, uprn, postcode, lodgement_date, a, {_sig('a')} AS sig
            FROM (SELECT lmk_key, uprn, postcode, lodgement_date, trim(split_part(address_key, '|', 1)) AS a
                  FROM mkt_uk.epc_certificate WHERE postcode IS NOT NULL AND total_floor_area_m2 IS NOT NULL) x""")
        ctx.conn.execute("CREATE INDEX ON p (postcode)")
        ctx.conn.execute("CREATE INDEX ON e (postcode, sig)")
        ctx.conn.execute("ANALYZE p")
        ctx.conn.execute("ANALYZE e")

        ctx.sql("ứng viên luật 1", """
            CREATE TEMP TABLE cand ON COMMIT DROP AS
            SELECT p.transaction_id, e.lmk_key, e.uprn, (p.n = e.a) AS exact,
                   CASE WHEN p.sig <> '' THEN 0.9 ELSE word_similarity(p.nm, e.a) END::real AS score
            FROM p JOIN e ON e.postcode = p.postcode AND e.sig = p.sig
            WHERE (p.sig <> '' AND (p.sw = '' OR e.a ~ ('\\m' || p.sw || '\\M')))
               OR (p.sig = '' AND p.nm <> '' AND word_similarity(p.nm, e.a) >= 0.8)""")
        ctx.conn.execute("CREATE INDEX ON cand (transaction_id)")
        ctx.conn.execute("ANALYZE cand")
        ctx.sql("ứng viên luật 2 (EPC thiếu số toà nhà)", """
            INSERT INTO cand
            SELECT p.transaction_id, e.lmk_key, e.uprn, false, 0.8
            FROM p JOIN e ON e.postcode = p.postcode AND e.sig = p.sig_saon
            WHERE p.sig_saon <> '' AND p.sig_saon <> p.sig AND length(p.bname) >= 4
              AND position(p.bname IN e.a) > 0
              AND NOT EXISTS (SELECT 1 FROM cand c WHERE c.transaction_id = p.transaction_id)""")
        ctx.conn.execute("ANALYZE cand")
        ambiguous = ctx.sql("giao dịch mơ hồ (> 1 UPRN)", """
            CREATE TEMP TABLE amb ON COMMIT DROP AS
            SELECT transaction_id FROM cand GROUP BY 1 HAVING count(DISTINCT uprn) > 1""")

        # Ghi vào bảng mới rồi đổi tên: TRUNCATE + bỏ FK sẽ giữ khoá AccessExclusive trên price_paid và
        # epc_certificate suốt bước ghi (chặn mọi SELECT, kể cả web). ADD CONSTRAINT FK chỉ cần ShareRowExclusive.
        ctx.conn.execute("DROP TABLE IF EXISTS mkt_uk.ppd_epc_match_new")
        ctx.conn.execute("""CREATE TABLE mkt_uk.ppd_epc_match_new (
            transaction_id uuid NOT NULL, lmk_key text NOT NULL,
            match_method text NOT NULL CHECK (match_method IN ('uprn', 'exact_address', 'fuzzy_address')),
            match_score real NOT NULL CHECK (match_score BETWEEN 0 AND 1),
            matched_at timestamptz NOT NULL DEFAULT now())""")
        n_match = ctx.sql("ghi ppd_epc_match (bảng mới)", """
            INSERT INTO mkt_uk.ppd_epc_match_new (transaction_id, lmk_key, match_method, match_score)
            SELECT DISTINCT ON (c.transaction_id) c.transaction_id, c.lmk_key,
                   CASE WHEN c.exact THEN 'exact_address' ELSE 'fuzzy_address' END,
                   CASE WHEN c.exact THEN 1 ELSE c.score END
            FROM cand c JOIN p ON p.transaction_id = c.transaction_id
            JOIN mkt_uk.epc_certificate x ON x.lmk_key = c.lmk_key
            WHERE NOT EXISTS (SELECT 1 FROM amb WHERE amb.transaction_id = c.transaction_id)
            ORDER BY c.transaction_id, c.exact DESC,
                     (x.lodgement_date > p.transfer_date + 180), abs(x.lodgement_date - p.transfer_date)""")
        ctx.sql("khoá chính + index", "ALTER TABLE mkt_uk.ppd_epc_match_new ADD PRIMARY KEY (transaction_id)")
        ctx.conn.execute("CREATE INDEX ON mkt_uk.ppd_epc_match_new (lmk_key)")
        ctx.sql("FK → price_paid", """ALTER TABLE mkt_uk.ppd_epc_match_new ADD FOREIGN KEY (transaction_id)
                                     REFERENCES mkt_uk.price_paid (transaction_id) ON DELETE CASCADE""")
        ctx.sql("FK → epc_certificate", """ALTER TABLE mkt_uk.ppd_epc_match_new ADD FOREIGN KEY (lmk_key)
                                           REFERENCES mkt_uk.epc_certificate (lmk_key) ON DELETE CASCADE""")
        ctx.conn.execute("ANALYZE mkt_uk.ppd_epc_match_new")

        # ---- kiểm tra tỉ lệ ghép (EPC có từ 10/2008 → đo trên giao dịch từ 2012)
        total, since, m_all, m_since = ctx.conn.execute("""
            SELECT count(*), count(*) FILTER (WHERE t.transfer_date >= '2012-01-01'),
                   count(m.transaction_id), count(m.transaction_id) FILTER (WHERE t.transfer_date >= '2012-01-01')
            FROM mkt_uk.price_paid t LEFT JOIN mkt_uk.ppd_epc_match_new m USING (transaction_id)""").fetchone()
        rate = m_since / since
        log.info("    ghép được %s/%s giao dịch (%.1f%%); từ 2012: %.1f%%; mơ hồ bỏ qua: %s",
                 f"{m_all:,}", f"{total:,}", m_all * 100 / total, rate * 100, f"{ambiguous:,}")
        if not 0.70 <= rate <= 0.98:
            raise LoadError(f"Tỉ lệ ghép PPD↔EPC từ 2012 bất thường: {rate:.1%} (kỳ vọng 70–98%)")
        by_method = dict(ctx.conn.execute("SELECT match_method, count(*) FROM mkt_uk.ppd_epc_match_new GROUP BY 1").fetchall())
        log.info("    theo cách ghép: %s", by_method)
        worst = ctx.conn.execute("""
            SELECT p.region_code, count(m.transaction_id)::float / count(*) r
            FROM mkt_uk.price_paid t JOIN mkt_uk.postcode p ON p.postcode = t.postcode
            LEFT JOIN mkt_uk.ppd_epc_match_new m USING (transaction_id)
            WHERE t.transfer_date >= '2012-01-01'
              AND (p.region_code LIKE 'E12%' OR p.region_code LIKE 'W92%')  -- bỏ mã giả (S99999999...) của postcode biên
            GROUP BY 1 HAVING count(*) >= 10000 ORDER BY 2 LIMIT 3""").fetchall()
        log.info("    vùng có tỉ lệ ghép thấp nhất: %s", [(r, round(v * 100, 1)) for r, v in worst])
        if worst and worst[0][1] < 0.55:
            raise LoadError(f"Vùng {worst[0][0]} chỉ ghép được {worst[0][1]:.0%} giao dịch từ 2012")
        # diện tích trung vị theo loại nhà phải theo thứ tự hợp lý: flat < terraced < semi < detached
        fa = dict(ctx.conn.execute("""
            SELECT t.property_type, percentile_cont(0.5) WITHIN GROUP (ORDER BY x.total_floor_area_m2)
            FROM mkt_uk.ppd_epc_match_new m JOIN mkt_uk.price_paid t USING (transaction_id)
            JOIN mkt_uk.epc_certificate x USING (lmk_key)
            WHERE t.transfer_date >= '2020-01-01' AND t.property_type <> 'O' GROUP BY 1""").fetchall())
        log.info("    diện tích trung vị (m²) theo loại: %s", {k: round(v) for k, v in fa.items()})
        if not (35 <= fa["F"] < fa["T"] < fa["S"] < fa["D"] <= 200):
            raise LoadError(f"Diện tích theo loại nhà bất thường: {fa}")

        # ---- £/m² theo khu, 24 tháng (cùng cửa sổ và cách gán khu với bước housing)
        last = ctx.scalar("SELECT max(transfer_date) FROM mkt_uk.price_paid WHERE ppd_category = 'A'")
        start = ctx.scalar("SELECT (%s::date - interval '24 months')::date", (last,))
        ctx.sql("giao dịch 24 tháng có diện tích", f"""
            CREATE TEMP TABLE sq ON COMMIT DROP AS
            SELECT t.postcode, t.price::float8 / x.total_floor_area_m2 AS ppsqm, x.total_floor_area_m2::float8 AS fa
            FROM mkt_uk.price_paid t JOIN mkt_uk.ppd_epc_match_new m USING (transaction_id)
            JOIN mkt_uk.epc_certificate x USING (lmk_key)
            WHERE t.ppd_category = 'A' AND t.property_type <> 'O' AND t.transfer_date > %s
              AND t.price::float8 / x.total_floor_area_m2 BETWEEN {PPSQM_RANGE[0]} AND {PPSQM_RANGE[1]}""", (start,))
        ctx.conn.execute("CREATE INDEX ON sq (postcode)")
        ctx.conn.execute("ANALYZE sq")
        union = " UNION ALL ".join(
            f"SELECT a.id area_id, s.ppsqm, s.fa FROM sq s JOIN mkt_uk.postcode p ON p.postcode = s.postcode "
            f"JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='{lvl}' AND a.code = {col}"
            for lvl, col in POSTCODE_LEVELS.items())
        radius = "CASE t.attrs->>'local_type' " + " ".join(f"WHEN '{k}' THEN {v}" for k, v in TOWN_RADIUS_M.items()) + " END"
        ctx.sql("£/m² trung vị theo khu", f"""
            CREATE TEMP TABLE sq_stats ON COMMIT DROP AS
            SELECT area_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY ppsqm) AS ppsqm,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY fa) AS fa, count(*) AS n
            FROM ({union}
                  UNION ALL
                  SELECT t.id, s.ppsqm, s.fa FROM core.geo_area t
                  JOIN mkt_uk.postcode p ON ST_DWithin(p.geom, t.centroid, ({radius}) / 55000.0)
                       AND ST_DWithin(p.geom::geography, t.centroid::geography, {radius}) AND p.status = 'live'
                  JOIN sq s ON s.postcode = p.postcode
                  WHERE t.market_code='uk' AND t.level_code='town' AND t.is_active) x
            GROUP BY area_id""")
        common = dict(category="housing", dataset="uk.land_registry.ppd", period_type="rolling_12m",
                      native_level="postcode_unit", aggregation="median_recompute", scope="uk.ew", scorable=False)
        register_metric(ctx, "uk.price.per_sqm", value_type="currency", unit="GBP", direction=-1,
                        name="Median price per m² (last 24 months)",
                        description="Sale price ÷ EPC total floor area, matched by address (Price Paid ↔ EPC)", **common)
        register_metric(ctx, "uk.price.floor_area", value_type="number", unit="m²",
                        name="Median floor area of homes sold (last 24 months)", **common)
        ids = ["uk.price.per_sqm", "uk.price.floor_area"]
        ctx.sql("xoá giá trị kỳ này", "DELETE FROM core.metric_value WHERE market_code='uk' AND metric_id = ANY(%s) AND period = %s",
                (ids, last))
        n_val = ctx.sql("ghi £/m² + diện tích", f"""
            INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, sample_size,
                                           is_suppressed, suppression_reason)
            SELECT 'uk', s.area_id, m.metric_id, %s, CASE WHEN s.n >= {MIN_SAMPLE} THEN round(m.v::numeric) END, s.n,
                   s.n < {MIN_SAMPLE}, CASE WHEN s.n < {MIN_SAMPLE} THEN 'small_sample' END
            FROM sq_stats s CROSS JOIN LATERAL (VALUES ('uk.price.per_sqm', s.ppsqm), ('uk.price.floor_area', s.fa)) m(metric_id, v)""",
                        (last,))

        def nat(metric, code):
            return ctx.scalar("""SELECT v.value_num FROM core.metric_value v JOIN core.geo_area a ON a.id = v.area_id
                WHERE v.metric_id = %s AND v.period = %s AND a.code = %s AND a.level_code IN ('nation','region','lad')""",
                              (metric, last, code))
        eng, wal, lon, kc = (nat("uk.price.per_sqm", c) for c in ("E92000001", "W92000004", "E12000007", "E09000020"))
        log.info("    £/m² 24 tháng: England £%s, Wales £%s, London £%s, Kensington & Chelsea £%s",
                 *(f"{v:,.0f}" if v else None for v in (eng, wal, lon, kc)))
        # số liệu tham khảo công khai: England ~£3.000–4.000/m², London ~£6.000–8.000, K&C > £12.000
        if not (eng and wal and lon and kc and 2_200 <= eng <= 5_000 and 1_500 <= wal <= 3_500
                and lon > 1.6 * eng and kc > lon):
            raise LoadError(f"£/m² bất thường: England {eng}, Wales {wal}, London {lon}, K&C {kc}")
        ctx.check_range("£/m² mọi khu", "core.metric_value v", "v.value_num", 300, 60_000,
                        where=f"v.metric_id = 'uk.price.per_sqm' AND v.period = '{last}'")
        # đổi bảng ở bước cuối: khoá do DROP TABLE giữ tới commit, ngay sau đây
        ctx.conn.execute("DROP TABLE mkt_uk.ppd_epc_match")
        ctx.conn.execute("ALTER TABLE mkt_uk.ppd_epc_match_new RENAME TO ppd_epc_match")
        for old, new in ctx.conn.execute("""SELECT c.relname, replace(c.relname, 'ppd_epc_match_new', 'ppd_epc_match')
                FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
                WHERE i.indrelid = 'mkt_uk.ppd_epc_match'::regclass""").fetchall():
            ctx.conn.execute(f'ALTER INDEX mkt_uk."{old}" RENAME TO "{new}"')
        ctx.conn.execute("""COMMENT ON TABLE mkt_uk.ppd_epc_match IS 'Kết quả ghép giao dịch ↔ EPC gần nhất trước ngày giao dịch.
            Nền tảng cho £/m² và AVM. Tạo lại toàn bộ bởi derive epc_match.'""")
        return {"matched": m_all, "match_rate_since_2012": round(rate, 4), "ambiguous": ambiguous,
                "by_method": by_method, "values": n_val, "period_end": str(last)}
