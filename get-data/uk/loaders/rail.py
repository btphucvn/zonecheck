"""Nạp ORR station usage → làm giàu POI ga (station.rail): mã CRS, slug /uk/station/{crs}-{tên}, lượt khách."""
from __future__ import annotations

import csv
import logging
import re
from collections import defaultdict
from datetime import date

from .base import LoadContext, LoadError, Loader, slug_sql
from .metrics import register_metric

log = logging.getLogger(__name__)


def _base(s: str) -> str:
    s = s.lower().replace("&", "and").replace("'", "").replace("’", "")
    s = re.sub(r"\[note.*?\]", "", s)
    return re.sub(r"\b(rail|railway) station\b|\bstation\b", "", s)


def norm(s: str) -> str:
    """Giữ nội dung trong ngoặc: 'Dorking (Deepdene)' → 'dorking deepdene'."""
    return re.sub(r"[^a-z0-9]+", " ", _base(s)).strip()


def norm_loose(s: str) -> str:
    """Bỏ phần trong ngoặc: 'Penrith (North Lakes)' → 'penrith'."""
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\(.*?\)", " ", _base(s))).strip()


def num(v: str):
    v = (v or "").replace(",", "").strip()
    return int(v) if v.isdigit() else None


class OrrStationUsageLoader(Loader):
    source = "orr_station_usage"
    depends_on = ("naptan", "boundaries_rgn", "boundaries_lad")
    description = "ORR Table 1410 → POI station.rail (attrs crs, slug) + poi_metric_value uk.rail.entries_exits / interchanges"

    def load(self, ctx: LoadContext) -> dict:
        lines = ctx.file(r"\.csv$").read_text(encoding="utf-8-sig").splitlines()
        rows = list(csv.reader(lines))
        h = next((i for i, r in enumerate(rows) if r and r[0] == "Station name"), None)
        if h is None:
            raise LoadError("ORR: không thấy dòng header 'Station name'")
        hdr = [re.sub(r"\s+", " ", c).strip() for c in rows[h]]
        col = lambda key: next(i for i, c in enumerate(hdr) if key.lower() in c.lower())  # noqa: E731
        i_all, i_int, i_tlc, i_reg, i_rank, i_nlc = (col("All tickets"), col("Interchanges"), col("Three Letter Code"),
                                                     col("Region"), col("Rank"), col("National Location Code"))
        orr = [r for r in rows[h + 1:] if r and r[0].strip()]
        crs = [r[i_tlc].strip() for r in orr]
        dup = {c for c in crs if crs.count(c) > 1}
        if dup or any(not re.fullmatch(r"[A-Z]{3}", c) for c in crs):
            raise LoadError(f"ORR: mã CRS trùng/sai định dạng: {sorted(dup)[:10]}")

        # Ga NaPTAN + vùng (region England hoặc nation) chứa ga, để phân biệt ga trùng tên
        stations = ctx.conn.execute("""
            SELECT p.id, p.name, coalesce(rg.name, nt.name), ST_X(p.geom), ST_Y(p.geom)
            FROM core.poi p
            LEFT JOIN core.geo_area rg ON rg.market_code='uk' AND rg.level_code='region' AND ST_Intersects(rg.geom, p.geom)
            LEFT JOIN core.geo_area nt ON nt.market_code='uk' AND nt.level_code='nation' AND ST_Intersects(nt.geom, p.geom)
                                          AND nt.code <> 'E92000001'
            WHERE p.market_code='uk' AND p.type_code='station.rail' AND p.status='open'""").fetchall()
        by_exact, by_loose = defaultdict(list), defaultdict(list)
        for pid, name, region, x, y in stations:
            by_exact[norm(name)].append((pid, region, x, y))
            by_loose[norm_loose(name)].append((pid, region, x, y))

        matches, unmatched, used = [], [], {}

        def pick(cands, region):
            if len(cands) > 1:
                cands = [c for c in cands if c[1] == region] or cands
            if len(cands) > 1:
                # NaPTAN có nhiều bản ghi cho cùng một ga lớn (mỗi nhóm sân ga một ATCO): nếu tất cả nằm trong
                # ~1 km thì là một ga → chọn bản ghi id nhỏ nhất; xa hơn → thật sự là các ga khác nhau, bỏ qua
                xs, ys = [c[2] for c in cands], [c[3] for c in cands]
                if (max(xs) - min(xs)) * 68 < 1 and (max(ys) - min(ys)) * 111 < 1:  # km xấp xỉ ở vĩ độ UK
                    return min(c[0] for c in cands)
                return None
            return cands[0][0] if cands else None

        pending = []
        for r in orr:  # lượt 1: khớp đầy đủ (giữ nội dung trong ngoặc)
            name, region = r[0].strip(), r[i_reg].strip()
            pid = pick(by_exact.get(norm(name), []), region)
            if pid is None:
                pending.append(r)
            elif pid in used:
                raise LoadError(f"ORR: ga NaPTAN {pid} bị ghép cho cả {used[pid]} và {name}")
            else:
                used[pid] = name
                matches.append((pid, r))
        for r in pending:  # lượt 2: khớp lỏng, chỉ vào ga chưa có chủ
            name, region = r[0].strip(), r[i_reg].strip()
            cands = [c for c in by_loose.get(norm_loose(name), []) if c[0] not in used]
            pid = pick(cands, region)
            if pid is None:
                unmatched.append((name, region, len(cands)))
            else:
                used[pid] = name
                matches.append((pid, r))
        ratio = len(matches) / len(orr)
        log.info("    ghép ORR ↔ NaPTAN: %s/%s (%.1f%%); chưa ghép: %s", len(matches), len(orr), ratio * 100,
                 unmatched[:30])
        if ratio < 0.97:
            raise LoadError(f"ORR: chỉ ghép được {ratio:.1%} ga (cần ≥ 97%)")

        period = date.fromisoformat(str(ctx.manifest.get("period_end") or "2025-03-31")[:10])
        total = sum(num(r[i_all]) or 0 for r in orr)
        log.info("    tổng lượt vào/ra toàn GB: %s", f"{total:,}")
        if not 500_000_000 <= total <= 4_000_000_000:
            raise LoadError(f"Tổng lượt vào/ra bất thường: {total:,}")
        biggest = max(orr, key=lambda r: num(r[i_all]) or 0)
        if not 30_000_000 <= (num(biggest[i_all]) or 0) <= 300_000_000:
            raise LoadError(f"Ga đông nhất bất thường: {biggest[0]} {biggest[i_all]}")

        for mid, name in (("uk.rail.entries_exits", "Station entries and exits per year"),
                          ("uk.rail.interchanges", "Station interchanges per year")):
            register_metric(ctx, mid, category="transport", dataset="uk.orr.station_usage", value_type="count",
                            period_type="financial_year", scope="uk.uk", name=name, scorable=False)
        ctx.conn.execute("UPDATE core.metric SET subject='poi' WHERE id LIKE 'uk.rail.%'")

        t = ctx.stage_table("orr", ["poi_id", "crs", "nlc", "orr_name", "region", "entries_exits", "interchanges",
                                    "rank"], {"poi_id": "bigint", "entries_exits": "bigint", "interchanges": "bigint",
                                              "rank": "int"})
        ctx.copy_rows(t, ["poi_id", "crs", "nlc", "orr_name", "region", "entries_exits", "interchanges", "rank"],
                      [(pid, r[i_tlc].strip(), r[i_nlc].strip(), r[0].strip(), r[i_reg].strip(), num(r[i_all]),
                        num(r[i_int]), num(r[i_rank])) for pid, r in matches], "COPY ORR")
        ctx.check_range("entries_exits", t, "entries_exits", 0, 300_000_000)
        ctx.sql("POI ga: crs + slug + attrs", f"""
            UPDATE core.poi p SET slug = lower(s.crs) || '-' || {slug_sql('s.orr_name')},
                   attrs = p.attrs || jsonb_strip_nulls(jsonb_build_object('crs', s.crs, 'nlc', s.nlc,
                       'orr_name', s.orr_name, 'orr_region', s.region, 'usage_rank', s.rank))
            FROM {t} s WHERE p.id = s.poi_id""")
        # ga không có trong ORR (ga đóng/di sản) không có trang riêng
        ctx.sql("bỏ slug ga không có trong ORR", f"""
            UPDATE core.poi p SET slug = NULL WHERE p.type_code='station.rail' AND p.slug IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM {t} s WHERE s.poi_id = p.id)""")
        n = ctx.sql("poi_metric_value lượt khách", f"""
            INSERT INTO core.poi_metric_value (poi_id, metric_id, period, value_num, release_id)
            SELECT poi_id, m.metric_id, %s, m.v, %s FROM {t}
            CROSS JOIN LATERAL (VALUES ('uk.rail.entries_exits', entries_exits::float8),
                                       ('uk.rail.interchanges', interchanges::float8)) m(metric_id, v)
            WHERE m.v IS NOT NULL
            ON CONFLICT (poi_id, metric_id, period) DO UPDATE SET value_num = EXCLUDED.value_num,
                release_id = EXCLUDED.release_id, computed_at = now()""", (period, ctx.release_id))
        ctx.stats["matched"] = len(matches)
        ctx.drop_stage("orr")
        return {"orr_stations": len(orr), "matched": len(matches), "unmatched": len(unmatched), "values": n,
                "total_entries_exits": total}
