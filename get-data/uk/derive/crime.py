"""Chỉ số tội phạm 12 tháng gần nhất theo LSOA → mọi cấp trang (theo thành phần dân số).

- Số vụ theo LSOA lấy trực tiếp từ data.police.uk (toạ độ đã ẩn danh, gắn LSOA 2021 bởi nguồn).
- Khu khác (sector, district, town, MSOA, LAD, region, nation): Σ số vụ LSOA × phần LSOA nằm trong khu.
- Tỉ lệ / 1.000 dân = số vụ / dân số Census 2021 (đã phân bổ ở bước membership).
- Lực lượng thiếu dữ liệu trong kỳ (crime_coverage_gap) → LSOA của lực lượng đó bị ẩn (is_suppressed).
  LSOA không có bản ghi nào trong 36 tháng (Greater Manchester Police không gửi dữ liệu) cũng bị ẩn.
- Ngoài 7 nhóm: tỉ lệ cho từng loại trong 14 loại của police (TYPES), để xếp hạng toàn quốc theo loại.
"""
from __future__ import annotations

import logging

from ..loaders.base import LoadContext, LoadError
from ..loaders.metrics import register_metric
from .base import Step

log = logging.getLogger(__name__)

GROUPS = {  # metric key → điều kiện crime_type (ASB tách riêng, không tính vào tổng tội phạm theo chuẩn ONS)
    "total": "crime_type <> 'Anti-social behaviour'",
    "violent": "crime_type IN ('Violence and sexual offences', 'Robbery', 'Possession of weapons')",
    "burglary": "crime_type = 'Burglary'",
    "vehicle": "crime_type = 'Vehicle crime'",
    "theft": "crime_type IN ('Other theft', 'Theft from the person', 'Bicycle theft', 'Shoplifting')",
    "damage": "crime_type = 'Criminal damage and arson'",
    "asb": "crime_type = 'Anti-social behaviour'",
}
# Từng loại tội phạm của police (14 loại) để xếp hạng toàn quốc theo loại. Burglary, vehicle, damage, asb đã là
# một loại duy nhất trong GROUPS; còn lại 10 loại thêm ở đây. Không dùng tính điểm (scorable=False).
TYPES = {
    "vso": ("Violence and sexual offences", "Violence and sexual offences"),
    "robbery": ("Robbery", "Robbery"),
    "weapons": ("Possession of weapons", "Possession of weapons"),
    "bicycle": ("Bicycle theft", "Bicycle theft"),
    "other_theft": ("Other theft", "Other theft"),
    "theft_person": ("Theft from the person", "Theft from the person"),
    "shoplifting": ("Shoplifting", "Shoplifting"),
    "public_order": ("Public order", "Public order"),
    "drugs": ("Drugs", "Drugs"),
    "other_crime": ("Other crime", "Other crime"),
}
GROUPS.update({k: f"crime_type = '{t}'" for k, (t, _) in TYPES.items()})
SINGLE = ("burglary", "vehicle", "damage", *TYPES)  # các loại cộng lại = total (không ASB)
LEVELS = ("msoa", "lad", "region", "nation", "sector", "district", "postal_area", "town")


class Crime(Step):
    name = "crime"
    depends_on = ("membership",)
    needs_sources = ("police", "police_force_areas")
    description = "Tội phạm 12 tháng: số vụ, tỉ lệ / 1.000 dân theo nhóm, xu hướng; ẩn khu thiếu dữ liệu nguồn"

    def run(self, ctx: LoadContext) -> dict:
        last = ctx.scalar("SELECT max(month) FROM mkt_uk.crime_incident")
        start = ctx.scalar("SELECT (%s::date - interval '11 months')::date", (last,))
        prev_start = ctx.scalar("SELECT (%s::date - interval '23 months')::date", (last,))
        log.info("    kỳ: %s → %s (so với 12 tháng trước từ %s)", start, last, prev_start)

        cases = ", ".join(f"count(*) FILTER (WHERE month >= %(s)s AND {cond}) AS {k}" for k, cond in GROUPS.items())
        ctx.sql("đếm theo LSOA", f"""
            CREATE TEMP TABLE lsoa_crime ON COMMIT DROP AS
            SELECT a.id AS area_id, {cases},
                   count(*) FILTER (WHERE month >= %(p)s AND month < %(s)s AND {GROUPS['total']}) AS total_prev
            FROM core.geo_area a
            LEFT JOIN mkt_uk.crime_incident c ON c.lsoa21_code = a.code AND c.month >= %(p)s
            WHERE a.market_code='uk' AND a.level_code='lsoa' AND a.is_active
            GROUP BY a.id""", {"s": start, "p": prev_start})
        ctx.conn.execute("CREATE INDEX ON lsoa_crime (area_id)")
        unmatched = ctx.scalar("""SELECT count(*) FROM mkt_uk.crime_incident c WHERE c.month >= %s
            AND c.lsoa21_code IS NOT NULL AND NOT EXISTS (SELECT 1 FROM core.geo_area a WHERE a.level_code='lsoa'
            AND a.code = c.lsoa21_code)""", (start,))
        n12 = ctx.scalar("SELECT count(*) FROM mkt_uk.crime_incident WHERE month >= %s", (start,))
        log.info("    vụ việc 12 tháng: %s; mã LSOA không khớp ranh giới 2021: %s", f"{n12:,}", f"{unmatched:,}")
        if unmatched > n12 * 0.01:
            raise LoadError(f"{unmatched:,} vụ có mã LSOA không khớp (> 1%) — kiểm tra phiên bản LSOA của police")
        types_seen = {r[0] for r in ctx.conn.execute(
            "SELECT DISTINCT crime_type FROM mkt_uk.crime_incident WHERE month >= %s", (start,))}
        unknown = types_seen - {t for t, _ in TYPES.values()} - {"Burglary", "Vehicle crime", "Criminal damage and arson", "Anti-social behaviour"}
        if unknown:
            raise LoadError(f"Loại tội phạm lạ trong 12 tháng (police đổi phân loại?): {sorted(unknown)}")
        bad = ctx.scalar(f"SELECT count(*) FROM lsoa_crime WHERE total <> {' + '.join(SINGLE)}")
        if bad:
            raise LoadError(f"{bad} LSOA có tổng từng loại ≠ tổng tội phạm (không ASB)")

        # Lực lượng của từng LSOA theo ranh giới Police Force Area chính thức (ONS) chứa LSOA. Không suy từ dữ liệu
        # tội phạm: LSOA của lực lượng không gửi dữ liệu (GMP) vẫn có vài bản ghi do BTP/lực lượng lân cận báo.
        forces = [r[0] for r in ctx.conn.execute("""SELECT DISTINCT reported_by FROM mkt_uk.crime_incident
            UNION SELECT police_force FROM mkt_uk.crime_coverage_gap""")]
        pfas = ctx.conn.execute("SELECT id, name FROM core.zone WHERE type_code = 'admin.police_force_area'").fetchall()
        if len(pfas) < 43:
            raise LoadError(f"Cần 43 Police Force Area, có {len(pfas)} — nạp police_force_areas trước")

        def norm(x: str) -> str:
            x = x.lower().replace("&", "and").replace("london, city of", "city of london")
            return " ".join(x.replace(",", " ").split())
        pfa_force = {}
        for zid, pname in pfas:
            hits = [f for f in forces if norm(f).startswith(norm(pname))]
            if len(hits) != 1:
                raise LoadError(f"PFA '{pname}' ghép được {hits} lực lượng (cần đúng 1)")
            pfa_force[zid] = hits[0]
        ctx.conn.execute("CREATE TEMP TABLE pfa_force (zone_id bigint, force text) ON COMMIT DROP")
        ctx.copy_rows("pfa_force", ["zone_id", "force"], list(pfa_force.items()), "COPY PFA → lực lượng")
        ctx.sql("lực lượng của từng LSOA", """
            CREATE TEMP TABLE lsoa_force ON COMMIT DROP AS
            SELECT DISTINCT ON (a.id) a.id AS area_id, f.force
            FROM core.geo_area a
            JOIN core.zone z ON z.type_code = 'admin.police_force_area' AND ST_Intersects(z.geom, ST_PointOnSurface(a.geom))
            JOIN pfa_force f ON f.zone_id = z.id
            WHERE a.market_code='uk' AND a.level_code='lsoa' AND a.is_active
            ORDER BY a.id, z.id""")
        unassigned = ctx.scalar("""SELECT count(*) FROM core.geo_area a WHERE a.level_code='lsoa' AND a.is_active
            AND NOT EXISTS (SELECT 1 FROM lsoa_force f WHERE f.area_id = a.id)""")
        if unassigned:
            raise LoadError(f"{unassigned} LSOA không nằm trong Police Force Area nào")
        ctx.sql("LSOA thiếu dữ liệu nguồn", """
            CREATE TEMP TABLE lsoa_gap ON COMMIT DROP AS
            SELECT f.area_id, 'force ' || f.force || ' missing months' AS reason
            FROM lsoa_force f
            WHERE EXISTS (SELECT 1 FROM mkt_uk.crime_coverage_gap g
                          WHERE g.police_force = f.force AND g.month BETWEEN %s AND %s)""", (start, last))
        ctx.conn.execute("CREATE INDEX ON lsoa_gap (area_id)")
        gaps = dict(ctx.conn.execute("SELECT reason, count(*) FROM lsoa_gap GROUP BY 1").fetchall())
        log.info("    LSOA bị ẩn: %s", gaps)
        gmp = gaps.get("force Greater Manchester Police missing months", 0)
        if not 1500 <= gmp <= 1900:  # Greater Manchester có ~1.700 LSOA
            raise LoadError(f"Số LSOA của GMP bị ẩn ({gmp}) không khớp ~1.700 LSOA của Greater Manchester")

        # ---- giá trị cho LSOA và các cấp (counts phân bổ theo trọng số dân số)
        # Khu cấp cao (region, nation...) có một phần LSOA thiếu dữ liệu: tỉ lệ tính trên phần dân số CÓ dữ liệu
        # (tử số và mẫu số cùng phạm vi); chỉ ẩn khi phần có dữ liệu < 50% dân số. Số vụ tuyệt đối ẩn khi thiếu > 5%.
        ctx.sql("bảng giá trị theo khu", f"""
            CREATE TEMP TABLE area_crime ON COMMIT DROP AS
            SELECT l.area_id, {", ".join(f"l.{k}::float8 AS {k}" for k in GROUPS)}, l.total_prev::float8 AS total_prev,
                   CASE WHEN g.area_id IS NULL THEN a.population ELSE 0 END::float8 AS pop_covered,
                   a.population::float8 AS population
            FROM lsoa_crime l JOIN core.geo_area a ON a.id = l.area_id LEFT JOIN lsoa_gap g ON g.area_id = l.area_id
            UNION ALL
            SELECT k.parent_id,
                   {", ".join(f"sum(CASE WHEN g.area_id IS NULL THEN l.{c} * k.weight ELSE 0 END)" for c in GROUPS)},
                   sum(CASE WHEN g.area_id IS NULL THEN l.total_prev * k.weight ELSE 0 END),
                   sum(CASE WHEN g.area_id IS NULL THEN k.weight * la.population ELSE 0 END),
                   sum(k.weight * la.population)
            FROM core.geo_area_link k
            JOIN lsoa_crime l ON l.area_id = k.child_id
            JOIN core.geo_area la ON la.id = k.child_id
            JOIN core.geo_area p ON p.id = k.parent_id AND p.level_code = ANY(%s)
            LEFT JOIN lsoa_gap g ON g.area_id = k.child_id
            WHERE k.relation = 'overlaps' AND k.weight_basis = 'population'
            GROUP BY k.parent_id""", (list(LEVELS),))

        names = {"total": "All crime (excl. ASB)", "violent": "Violent crime", "burglary": "Burglary",
                 "vehicle": "Vehicle crime", "theft": "Theft", "damage": "Criminal damage and arson",
                 "asb": "Anti-social behaviour", **{k: label for k, (_, label) in TYPES.items()}}
        for k, label in names.items():
            scorable = k not in TYPES
            register_metric(ctx, f"uk.crime.{k}_12m", category="safety", dataset="uk.police.street_crime",
                            value_type="count", period_type="rolling_12m", native_level="lsoa", aggregation="sum",
                            scope="uk.ew", name=f"{label}: incidents in last 12 months", scorable=False)
            register_metric(ctx, f"uk.crime.{k}_rate", category="safety", dataset="uk.police.street_crime",
                            value_type="rate", unit="per 1,000 residents", decimals=1, direction=-1,
                            period_type="rolling_12m", native_level="lsoa", aggregation="weighted_mean",
                            scope="uk.ew", name=f"{label} rate per 1,000 residents (12 months)", scorable=scorable)
        register_metric(ctx, "uk.crime.total_change_pct", category="safety", dataset="uk.police.street_crime",
                        value_type="percent", unit="%", decimals=0, direction=-1, period_type="rolling_12m",
                        native_level="lsoa", scope="uk.ew", name="Change in crime vs previous 12 months",
                        scorable=False)

        metric_ids = [f"uk.crime.{k}_{s}" for k in GROUPS for s in ("12m", "rate")] + ["uk.crime.total_change_pct"]
        ctx.sql("xoá giá trị kỳ này", "DELETE FROM core.metric_value WHERE market_code='uk' AND metric_id = ANY(%s) AND period = %s",
                (metric_ids, last))
        rows = []
        for k in GROUPS:
            rows.append(f"('uk.crime.{k}_12m', c.{k}, c.pop_covered < 0.95 * c.population)")
            rows.append(f"('uk.crime.{k}_rate', CASE WHEN c.pop_covered >= 50 THEN c.{k} * 1000.0 / c.pop_covered END, "
                        f"c.pop_covered < 0.5 * c.population)")
        rows.append("('uk.crime.total_change_pct', CASE WHEN c.total_prev >= 20 THEN (c.total - c.total_prev) * 100.0 / c.total_prev END, "
                    "c.pop_covered < 0.5 * c.population)")
        n = ctx.sql("ghi metric_value tội phạm", f"""
            INSERT INTO core.metric_value (market_code, area_id, metric_id, period, value_num, value_json, sample_size,
                                           is_suppressed, suppression_reason)
            SELECT 'uk', c.area_id, m.metric_id, %s, CASE WHEN m.supp THEN NULL ELSE m.v END,
                   CASE WHEN c.pop_covered < c.population AND NOT m.supp
                        THEN jsonb_build_object('population_coverage', round((c.pop_covered / nullif(c.population, 0))::numeric, 3)) END,
                   c.total::int, m.supp, CASE WHEN m.supp THEN 'source_suppressed' END
            FROM area_crime c CROSS JOIN LATERAL (VALUES {", ".join(rows)}) m(metric_id, v, supp)""", (last,))

        # ---- kiểm tra hợp lý
        ew = ctx.conn.execute("""SELECT a.code, v.value_num FROM core.metric_value v JOIN core.geo_area a ON a.id = v.area_id
            WHERE v.metric_id='uk.crime.total_rate' AND v.period=%s AND a.level_code='nation'""", (last,)).fetchall()
        log.info("    tỉ lệ tội phạm (không ASB) / 1.000 dân theo nation: %s", ew)
        if len(ew) != 2 or any(v is None for _, v in ew):
            raise LoadError(f"England/Wales phải đều có tỉ lệ tội phạm: {ew}")
        ctx.check_range("tỉ lệ nation", "core.metric_value v JOIN core.geo_area a ON a.id = v.area_id",
                        "v.value_num", 40, 150,
                        where=f"v.metric_id='uk.crime.total_rate' AND v.period='{last}' AND a.level_code='nation'")
        ctx.check_range("tỉ lệ LSOA (không âm)", "core.metric_value v", "v.value_num", 0, 100000,
                        where=f"v.metric_id LIKE 'uk.crime.%%_rate' AND v.period='{last}'")
        london = ctx.scalar("""SELECT v.value_num FROM core.metric_value v JOIN core.geo_area a ON a.id = v.area_id
            WHERE v.metric_id='uk.crime.total_rate' AND v.period=%s AND a.code='E12000007'""", (last,))
        sw = ctx.scalar("""SELECT v.value_num FROM core.metric_value v JOIN core.geo_area a ON a.id = v.area_id
            WHERE v.metric_id='uk.crime.total_rate' AND v.period=%s AND a.code='E12000009'""", (last,))
        log.info("    London %.1f vs South West %.1f / 1.000 dân", london or 0, sw or 0)
        if not (london and sw and london > sw):
            raise LoadError(f"Kiểm tra định hướng thất bại: London ({london}) không cao hơn South West ({sw})")
        return {"period_end": str(last), "values": n, "lsoa_suppressed": gaps, "incidents_12m": n12}
