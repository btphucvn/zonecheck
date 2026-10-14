"""Lịch sử tội phạm theo LSOA 2021 × năm × loại (12/2010 → nay) → mkt_uk.crime_lsoa_year + mkt_uk.crime_lsoa_year_cover.

- 12/2010–08/2023: crime_lsoa_year.csv.gz dựng ở máy local từ archive police (uk/sources/police_history.py).
- Từ 09/2023: cộng thêm từ mkt_uk.crime_incident (cùng nguồn, đã nạp từng vụ).
- Độ phủ: số tháng trong năm mà LAD (2022) của LSOA có ít nhất một vụ được ghi nhận. Năm < 12 tháng (lực lượng
  ngừng gửi dữ liệu, như Greater Manchester từ 07/2019, hoặc năm đang dở) không dùng để tính xu hướng.
"""
from __future__ import annotations

import csv
import gzip
import json
import logging
import re
from collections import defaultdict

from .base import LoadContext, LoadError, Loader

log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS mkt_uk.crime_lsoa_year (
    lsoa21 text NOT NULL, year smallint NOT NULL, crime_type text NOT NULL, n real NOT NULL,
    PRIMARY KEY (lsoa21, year, crime_type)
);
CREATE TABLE IF NOT EXISTS mkt_uk.crime_lsoa_year_cover (
    lsoa21 text NOT NULL, year smallint NOT NULL, months smallint NOT NULL,
    PRIMARY KEY (lsoa21, year)
);
COMMENT ON TABLE mkt_uk.crime_lsoa_year IS 'Số vụ police.uk theo LSOA 2021 × năm × loại, 12/2010 → nay (LSOA 2011 tách → chia đều).';
COMMENT ON TABLE mkt_uk.crime_lsoa_year_cover IS 'Số tháng có dữ liệu police của LAD chứa LSOA trong năm; chỉ năm = 12 tháng mới dùng cho xu hướng.'"""


class PoliceHistoryLoader(Loader):
    source = "police_history"
    depends_on = ("police",)
    description = "Lịch sử tội phạm LSOA × năm × loại → mkt_uk.crime_lsoa_year (+ độ phủ tháng)"

    def load(self, ctx: LoadContext) -> dict:
        lad_of: dict[str, str] = {}
        for f in json.loads(ctx.file(r"lsoa11_lsoa21\.geojson$").read_text())["features"]:
            p = f["properties"]
            lad_of[p["LSOA21CD"]] = p["LAD22CD"]
        with gzip.open(ctx.file(r"crime_lsoa_year\.csv\.gz$"), "rt", newline="") as fh:
            rows = [(r["lsoa21"], int(r["year"]), r["crime_type"], float(r["n"])) for r in csv.DictReader(fh)]
        years = sorted({r[1] for r in rows})
        log.info("    %s dòng, năm %s–%s", f"{len(rows):,}", years[0], years[-1])
        if years[0] != 2010 or years[-1] != 2023:
            raise LoadError(f"Khoảng năm bất thường: {years}")
        ctx.conn.execute(DDL)
        st = ctx.stage_table("chy", ["lsoa21", "year", "crime_type", "n"], {"year": "int", "n": "float8"})
        ctx.copy_rows(st, ["lsoa21", "year", "crime_type", "n"], rows, "COPY lịch sử")
        # tháng từ 09/2023 lấy từ từng vụ đã nạp
        ctx.sql("cộng thêm từ crime_incident (≥ 09/2023)", f"""
            INSERT INTO {st} SELECT lsoa21_code, extract(year FROM month)::int, crime_type, count(*)
            FROM mkt_uk.crime_incident WHERE month >= '2023-09-01' AND lsoa21_code IS NOT NULL GROUP BY 1, 2, 3""")
        ctx.sql("thay mkt_uk.crime_lsoa_year", "TRUNCATE mkt_uk.crime_lsoa_year")
        n = ctx.sql("ghi mkt_uk.crime_lsoa_year", f"""
            INSERT INTO mkt_uk.crime_lsoa_year SELECT lsoa21, year, crime_type, sum(n) FROM {st}
            WHERE lsoa21 IN (SELECT code FROM core.geo_area WHERE market_code = 'uk' AND level_code = 'lsoa')
            GROUP BY 1, 2, 3""")
        # độ phủ: lực lượng cảnh sát của LSOA (Police Force Area chứa LSOA) có gửi dữ liệu tháng đó không.
        # Không đo bằng "tháng có vụ trong khu": BTP vẫn báo vụ trên đường sắt ở khu lực lượng không gửi dữ liệu.
        slug = lambda x: re.sub(r"[^a-z0-9]+", "-", x.lower().replace("&", "and")).strip("-")  # noqa: E731
        alias = {"london-city-of": "city-of-london", "metropolitan-police": "metropolitan"}
        force_months: dict[str, set] = defaultdict(set)
        with open(ctx.file(r"force_months\.csv$"), newline="") as fh:
            for r in csv.DictReader(fh):
                force_months[r["force"]].add(r["month"])
        pfas = ctx.conn.execute("SELECT id, name FROM core.zone WHERE type_code = 'admin.police_force_area'").fetchall()
        pfa_slug = {zid: alias.get(slug(n), slug(n)) for zid, n in pfas}
        missing = {n for zid, n in pfas if pfa_slug[zid] not in force_months}
        if missing or len(pfas) < 43:
            raise LoadError(f"PFA không ghép được mã lực lượng police: {sorted(missing)} (có {sorted(force_months)[:50]})")
        # tháng ≥ 09/2023: mọi tháng có dữ liệu trừ tháng lực lượng bị thiếu (crime_coverage_gap, tên đầy đủ)
        recent = [r[0] for r in ctx.conn.execute(
            "SELECT DISTINCT to_char(month, 'YYYY-MM') FROM mkt_uk.crime_incident WHERE month >= '2023-09-01' ORDER BY 1")]
        gaps = ctx.conn.execute("SELECT police_force, to_char(month, 'YYYY-MM') FROM mkt_uk.crime_coverage_gap").fetchall()
        norm = lambda x: " ".join(x.lower().replace("&", "and").replace(",", " ").split())  # noqa: E731
        for zid, name in pfas:
            key = norm(name.replace("London, City of", "City of London"))
            gap = {m for f, m in gaps if norm(f).startswith(key)}
            force_months[pfa_slug[zid]] |= {m for m in recent if m not in gap}
        lsoa_force = dict(ctx.conn.execute("""
            SELECT DISTINCT ON (a.id) a.code, z.id FROM core.geo_area a
            JOIN core.zone z ON z.type_code = 'admin.police_force_area' AND ST_Intersects(z.geom, ST_PointOnSurface(a.geom))
            WHERE a.market_code = 'uk' AND a.level_code = 'lsoa' AND a.is_active ORDER BY a.id, z.id""").fetchall())
        by_year: dict[tuple[str, int], int] = defaultdict(int)
        for f, ms in force_months.items():
            for m in ms:
                by_year[(f, int(m[:4]))] += 1
        cover = [(code, y, by_year.get((pfa_slug[zid], y), 0)) for code, zid in lsoa_force.items() for y in range(2010, 2027)
                 if by_year.get((pfa_slug[zid], y))]
        log.info("    độ phủ: %s LSOA gán lực lượng, %s dòng LSOA × năm", f"{len(lsoa_force):,}", f"{len(cover):,}")
        ctx.sql("thay độ phủ", "TRUNCATE mkt_uk.crime_lsoa_year_cover")
        ctx.copy_rows("mkt_uk.crime_lsoa_year_cover", ["lsoa21", "year", "months"], cover, "COPY độ phủ")
        ctx.conn.execute("CREATE TEMP TABLE lsoa_lad (lsoa21 text, lad22 text) ON COMMIT DROP")
        ctx.copy_rows("lsoa_lad", ["lsoa21", "lad22"], list(lad_of.items()), "COPY LSOA → LAD 2022")
        # kiểm tra: tổng E&W theo năm hợp lý (police.uk ~5–6 triệu vụ/năm kể cả ASB) và Greater Manchester thiếu từ 2020
        tot = dict(ctx.conn.execute("SELECT year, sum(n) FROM mkt_uk.crime_lsoa_year GROUP BY 1 ORDER BY 1").fetchall())
        log.info("    tổng theo năm: %s", {y: round(v / 1e6, 2) for y, v in tot.items()})
        for y in range(2011, 2026):
            if not 3_500_000 <= tot.get(y, 0) <= 8_000_000:
                raise LoadError(f"Tổng số vụ năm {y} bất thường: {tot.get(y)}")
        gm = ctx.scalar("SELECT max(months) FROM mkt_uk.crime_lsoa_year_cover c JOIN lsoa_lad l USING (lsoa21) WHERE l.lad22 = 'E08000003' AND year = 2021")
        log.info("    Manchester (E08000003) năm 2021: %s tháng có dữ liệu (kỳ vọng 0 hoặc thiếu)", gm)
        if gm is not None and gm >= 12:
            raise LoadError("Manchester 2021 đủ 12 tháng — kiểm tra lại độ phủ (GMP không gửi dữ liệu 2020–)")
        wm = ctx.scalar("SELECT min(months) FROM mkt_uk.crime_lsoa_year_cover c JOIN lsoa_lad l USING (lsoa21) WHERE l.lad22 = 'E09000033' AND year = 2021")
        log.info("    Westminster (E09000033) năm 2021: %s tháng (kỳ vọng 12)", wm)
        if wm != 12:
            raise LoadError(f"Westminster 2021 có {wm} tháng — độ phủ Met Police sai")
        ctx.drop_stage("chy")
        return {"rows": n, "cover_rows": len(cover), "years": [years[0], 2026]}
