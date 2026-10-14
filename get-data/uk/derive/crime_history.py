"""Xu hướng tội phạm theo năm cho mọi khu (2011 → năm đủ 12 tháng gần nhất) → mkt_uk.crime_area_year.

Từ mkt_uk.crime_lsoa_year (+ độ phủ): chỉ LSOA-năm mà lực lượng cảnh sát gửi đủ 12 tháng mới được tính; khu
(sector, district, ward, town, MSOA, LAD, region, nation) = Σ LSOA × phần dân số trong khu, tỉ lệ / 1.000 dân trên phần
dân số có dữ liệu, bỏ năm khi phần đó < 50% dân số khu. Tính sẵn vì cộng ~75 nghìn LSOA-năm cho London mỗi lần
xem trang mất ~30 giây.
"""
from __future__ import annotations

import logging

from ..loaders.base import LoadContext, LoadError
from .base import Step

log = logging.getLogger(__name__)

TYPES = {"total": None, "vso": "Violence and sexual offences", "robbery": "Robbery", "weapons": "Possession of weapons"}
LEVELS = ("msoa", "lad", "region", "nation", "sector", "district", "postal_area", "town", "ward")
DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.crime_area_year (
    area_id bigint NOT NULL REFERENCES core.geo_area (id) ON DELETE CASCADE,
    year smallint NOT NULL,
    k text NOT NULL,                 -- total (không ASB) | vso | robbery | weapons
    rate real NOT NULL,              -- vụ / 1.000 dân trên phần dân số có dữ liệu
    coverage real NOT NULL,          -- phần dân số khu có dữ liệu đủ 12 tháng
    PRIMARY KEY (area_id, k, year)
);
COMMENT ON TABLE mkt_uk.crime_area_year IS 'Tỉ lệ tội phạm theo năm cho mọi khu (từ crime_lsoa_year, chỉ LSOA-năm đủ 12 tháng). k: total = không ASB; vso, robbery, weapons từ 2014.'"""


class CrimeHistory(Step):
    name = "crime_history"
    depends_on = ("membership",)
    needs_sources = ("police_history",)
    description = "Xu hướng tội phạm theo năm (tổng + bạo lực, cướp, vũ khí) cho mọi khu → mkt_uk.crime_area_year"

    def run(self, ctx: LoadContext) -> dict:
        ctx.conn.execute(DDL)
        def cond(t: str | None) -> str:
            return "y.crime_type <> 'Anti-social behaviour'" if t is None else f"y.crime_type = '{t}' AND y.year >= 2014"
        cases = ", ".join(f"sum(y.n) FILTER (WHERE {cond(t)}) AS {k}" for k, t in TYPES.items())
        ctx.sql("LSOA × năm đủ 12 tháng", f"""
            CREATE TEMP TABLE ly ON COMMIT DROP AS
            SELECT a.id AS lsoa_id, c.year, coalesce(a.population, 0)::float8 AS pop, {cases}
            FROM mkt_uk.crime_lsoa_year_cover c
            JOIN core.geo_area a ON a.market_code = 'uk' AND a.level_code = 'lsoa' AND a.code = c.lsoa21
            JOIN mkt_uk.crime_lsoa_year y ON y.lsoa21 = c.lsoa21 AND y.year = c.year
            WHERE c.months = 12
            GROUP BY a.id, c.year, a.population""")
        ctx.conn.execute("CREATE INDEX ON ly (lsoa_id)")
        ctx.conn.execute("ANALYZE ly")
        ctx.sql("thành phần khu (LSOA chính nó + liên kết theo dân số)", """
            CREATE TEMP TABLE comp ON COMMIT DROP AS
            SELECT id AS lsoa_id, id AS area_id, 1::float8 AS w FROM core.geo_area WHERE market_code = 'uk' AND level_code = 'lsoa'
            UNION ALL
            SELECT k.child_id, k.parent_id, k.weight FROM core.geo_area_link k
            JOIN core.geo_area p ON p.id = k.parent_id AND p.level_code = ANY(%s)
            WHERE k.relation = 'overlaps' AND k.weight_basis = 'population' AND k.weight > 0""", (list(LEVELS),))
        ctx.conn.execute("CREATE INDEX ON comp (lsoa_id)")
        ctx.sql("dân số khu", """
            CREATE TEMP TABLE apop ON COMMIT DROP AS
            SELECT c.area_id, sum(c.w * coalesce(a.population, 0))::float8 AS pop
            FROM comp c JOIN core.geo_area a ON a.id = c.lsoa_id GROUP BY 1""")
        ctx.conn.execute("CREATE INDEX ON apop (area_id)")
        ctx.sql("thay dữ liệu", "TRUNCATE mkt_uk.crime_area_year")
        sums = ", ".join(f"sum(l.{k} * c.w) AS {k}" for k in TYPES)
        vals = ", ".join(f"('{k}', x.{k})" for k in TYPES)
        n = ctx.sql("tỉ lệ theo năm", f"""
            INSERT INTO mkt_uk.crime_area_year (area_id, year, k, rate, coverage)
            SELECT x.area_id, x.year, v.k, 1000 * v.n / x.covered, x.covered / p.pop
            FROM (SELECT c.area_id, l.year, sum(l.pop * c.w) AS covered, {sums}
                  FROM comp c JOIN ly l ON l.lsoa_id = c.lsoa_id GROUP BY 1, 2) x
            JOIN apop p ON p.area_id = x.area_id
            CROSS JOIN LATERAL (VALUES {vals}) v(k, n)
            WHERE p.pop > 0 AND x.covered >= 0.5 * p.pop AND x.covered > 0 AND v.n IS NOT NULL""")
        ctx.conn.execute("ANALYZE mkt_uk.crime_area_year")
        # kiểm tra: England (không ASB) theo năm nằm trong khoảng hợp lý, London cao hơn South West
        eng = dict(ctx.conn.execute("""SELECT y.year, y.rate FROM mkt_uk.crime_area_year y JOIN core.geo_area a ON a.id = y.area_id
            WHERE a.code = 'E92000001' AND y.k = 'total' ORDER BY 1""").fetchall())
        log.info("    England / 1.000 dân theo năm: %s", {k: round(v, 1) for k, v in eng.items()})
        if not eng or any(not 40 <= v <= 130 for v in eng.values()):
            raise LoadError(f"Tỉ lệ England theo năm bất thường: {eng}")
        ldn = ctx.scalar("""SELECT y.rate FROM mkt_uk.crime_area_year y JOIN core.geo_area a ON a.id = y.area_id
            WHERE a.code = 'E12000007' AND y.k = 'total' AND y.year = 2019""")
        sw = ctx.scalar("""SELECT y.rate FROM mkt_uk.crime_area_year y JOIN core.geo_area a ON a.id = y.area_id
            WHERE a.code = 'E12000009' AND y.k = 'total' AND y.year = 2019""")
        log.info("    2019: London %.1f, South West %.1f", ldn or 0, sw or 0)
        if not (ldn and sw and ldn > sw):
            raise LoadError(f"London 2019 ({ldn}) không cao hơn South West ({sw})")
        return {"rows": n, "years": [min(eng), max(eng)]}
