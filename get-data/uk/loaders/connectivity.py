"""Nạp DfT Transport connectivity metric 2025 (ODS ~1 GB, đọc streaming) → metric uk.tcm.<phương tiện>_<điểm đến>."""
from __future__ import annotations

import logging
import re
from datetime import date

from common.ods import iter_ods_rows

from .base import LoadContext, LoadError, Loader
from .metrics import MV_COLS, insert_values, mv_stage, register_metric

log = logging.getLogger(__name__)

SHEETS = {"OA": ("oa", "OA21CD", 188880), "LSOA": ("lsoa", "LSOA21CD", 35672)}


def metric_key(col: str) -> tuple[str, str]:
    slug = lambda x: re.sub(r"[^a-z0-9]+", "_", x.lower().replace("&", "and")).strip("_")  # noqa: E731
    if col.strip().lower() == "overall":  # điểm tổng mọi phương tiện, mọi điểm đến
        return "uk.tcm.overall", "Connectivity score: overall (all modes)"
    m = re.match(r"^(.*?)\s*\((.*?)\)\s*$", col.strip())
    if not m:
        raise LoadError(f"Tên cột connectivity không đúng mẫu 'Đích (phương tiện)' hoặc 'Overall': {col!r}")
    dest, mode = m.group(1), m.group(2)
    return f"uk.tcm.{slug(mode)}_{slug(dest)}", f"Connectivity score: {dest.replace('&', 'and')} by {mode}"


class ConnectivityLoader(Loader):
    source = "transport_connectivity"
    depends_on = ("boundaries_oa21", "boundaries_lsoa21")
    description = "DfT connectivity 2025 → core.metric_value theo OA và LSOA (0–100, cao = kết nối tốt)"

    def load(self, ctx: LoadContext) -> dict:
        f = ctx.file(r"\.ods$")
        period = date(2025, 1, 1)
        t = mv_stage(ctx, "mv_tcm")
        metrics, stats = {}, {}
        for sheet, (level, code_col, expected) in SHEETS.items():
            header, n_rows, odd = None, 0, 0

            def rows():
                nonlocal header, n_rows, odd
                for r in iter_ods_rows(f, sheet):
                    if header is None:
                        if r and r[0] == code_col:
                            header = [str(c).strip() for c in r]
                            for c in header[1:]:
                                metrics.setdefault(c, metric_key(c))
                        continue
                    if not r or not re.match(r"^[EW]0\d{7}$", str(r[0])):
                        continue
                    n_rows += 1
                    for c, v in zip(header[1:], r[1:]):
                        try:
                            val = float(v) if v not in (None, "") else None
                        except ValueError:
                            odd += 1
                            continue
                        if val is not None:
                            yield (level, r[0], metrics[c][0], period, val, None)
            ctx.copy_rows(t, MV_COLS, rows(), f"stream {sheet} ({f.name})")
            if header is None:
                raise LoadError(f"Sheet {sheet}: không thấy dòng header '{code_col}'")
            if abs(n_rows - expected) > expected * 0.001:
                raise LoadError(f"Sheet {sheet}: {n_rows} khu, kỳ vọng ~{expected}")
            if odd > n_rows * 0.01:
                raise LoadError(f"Sheet {sheet}: {odd} giá trị không đọc được")
            stats[level] = {"areas": n_rows, "columns": len(header) - 1, "odd": odd}
            log.info("    %s: %s khu × %s cột, %s giá trị lạ", sheet, f"{n_rows:,}", len(header) - 1, odd)

        for col, (mid, name) in metrics.items():
            register_metric(ctx, mid, category="transport", dataset="uk.dft.connectivity", value_type="index",
                            decimals=1, direction=1, period_type="snapshot", native_level="oa", aggregation="mean",
                            scope="uk.ew", name=name, description=f"DfT Transport connectivity metric 2025, cột '{col}'")
        ctx.conn.execute(f"CREATE INDEX ON {t} (metric_id, level)")
        ctx.conn.execute(f"ANALYZE {t}")
        # ---- kiểm tra hợp lý
        ctx.check_range("điểm connectivity", t, "value_num", 0, 100)
        for col, (mid, _) in metrics.items():
            ctx.check_not_null_ratio(mid, f"(SELECT a.code FROM core.geo_area a WHERE a.market_code='uk' "
                                          f"AND a.level_code='lsoa' AND a.is_active) a LEFT JOIN {t} s "
                                          f"ON s.level='lsoa' AND s.code=a.code AND s.metric_id='{mid}'",
                                     "s.value_num", 0.95)
        overall = "uk.tcm.overall" if "uk.tcm.overall" in {m for m, _ in metrics.values()} else \
            next((m for c, (m, _) in metrics.items() if c.lower().startswith("overall")), None)
        if overall:
            london, rest = ctx.conn.execute(f"""
                SELECT avg(s.value_num) FILTER (WHERE r.code = 'E12000007'), avg(s.value_num) FILTER (WHERE r.code <> 'E12000007')
                FROM {t} s
                JOIN core.geo_area a ON a.market_code='uk' AND a.level_code='lsoa' AND a.code = s.code
                JOIN core.geo_area_link l1 ON l1.child_id = a.id
                JOIN core.geo_area m ON m.id = l1.parent_id AND m.level_code = 'msoa'
                JOIN core.geo_area_link l2 ON l2.child_id = m.id
                JOIN core.geo_area d ON d.id = l2.parent_id AND d.level_code = 'lad'
                JOIN core.geo_area_link l3 ON l3.child_id = d.id
                JOIN core.geo_area r ON r.id = l3.parent_id AND r.level_code = 'region'
                WHERE s.level = 'lsoa' AND s.metric_id = %s""", (overall,)).fetchone()
            log.info("    %s: London %.1f vs phần còn lại England %.1f", overall, london or 0, rest or 0)
            if london is None or rest is None or london <= rest:
                raise LoadError(f"Kiểm tra định hướng thất bại: London ({london}) không cao hơn phần còn lại ({rest})")
        n, unmatched = insert_values(ctx, t, "connectivity")
        if unmatched:
            raise LoadError(f"{unmatched} giá trị không khớp mã OA/LSOA")
        ctx.drop_stage("mv_tcm")
        return {"values": n, "metrics": len(metrics), **stats}
