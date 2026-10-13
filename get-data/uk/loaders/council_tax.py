"""Nạp council tax → mkt_uk.council_tax_rate (band theo LA) + metric uk.ctax.* (Band D theo LA, số nhà theo band)."""
from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from datetime import date

from common.ods import iter_ods_rows

from .base import LoadContext, LoadError, Loader
from .metrics import MV_COLS, insert_values, mv_stage, register_metric

log = logging.getLogger(__name__)

# Tỉ lệ luật định so với Band D (England A–H; Wales thêm I)
RATIO = {"A": 6 / 9, "B": 7 / 9, "C": 8 / 9, "D": 1.0, "E": 11 / 9, "F": 13 / 9, "G": 15 / 9, "H": 18 / 9, "I": 21 / 9}
CTSOP_LEVEL = {"LSOA": "lsoa", "MSOA": "msoa", "LAUA": "lad", "REGL": "region", "NATL": "nation"}


class CouncilTaxLoader(Loader):
    source = "council_tax"
    depends_on = ("boundaries_lad", "boundaries_lsoa21", "boundaries_msoa21")
    description = "Council tax England (Table 9) + Wales (Table 1) + VOA CTSOP1.1 → council_tax_rate + metric uk.ctax.*"

    def load(self, ctx: LoadContext) -> dict:
        fy = ctx.version                                   # '2026-27'
        fy_db = fy.replace("-", "/")                        # '2026/27' (CHECK của bảng)
        period = date(int(fy[:4]), 4, 1)
        lads = {code: name for code, name in ctx.conn.execute(
            "SELECT code, name FROM core.geo_area WHERE market_code='uk' AND level_code='lad' AND is_active")}

        # ---------- England Table 9
        rates, bad_ratio = [], []
        header = None
        for r in iter_ods_rows(ctx.file(r"england_tables_1_9\.ods$"), "Table_9"):
            if header is None:
                if r and r[0] == "E Code":
                    header = [str(c).strip() for c in r]
                continue
            if len(r) < 2 or not str(r[1]).startswith("E0"):
                continue
            row = dict(zip(header, r + [None] * (len(header) - len(r))))
            if any(row.get(f"Band {b}") is None for b in "ABCDEFGH"):
                raise LoadError(f"Table_9: thiếu giá trị band ở dòng {r[:4]}")
            amounts = {b: float(row[f"Band {b}"]) for b in "ABCDEFGH"}
            for b, v in amounts.items():
                if abs(v - amounts["D"] * RATIO[b]) > 0.05:
                    bad_ratio.append((row["Authority"], b, v, round(amounts["D"] * RATIO[b], 2)))
                rates.append((row["ONS Code"], b, v))
        if header is None:
            raise LoadError("Table_9: không thấy header 'E Code'")
        n_eng = len(rates) // 8
        log.info("    England: %s billing authority", n_eng)
        if bad_ratio:
            raise LoadError(f"Tỉ lệ band sai luật định ở {len(bad_ratio)} ô, ví dụ {bad_ratio[:5]}")
        if not 280 <= n_eng <= 330:
            raise LoadError(f"Số billing authority England bất thường: {n_eng}")

        # ---------- Wales Table 1 (Band D theo tên authority → LAD Wales)
        import openpyxl
        wb = openpyxl.load_workbook(ctx.file(r"wales_levels\.xlsx$"), read_only=True)
        wales_by_name = {n.lower().replace("&", "and"): c for c, n in lads.items() if c.startswith("W")}
        alias = {"isle of anglesey": "isle of anglesey", "rhondda cynon taf": "rhondda cynon taf",
                 "vale of glamorgan": "the vale of glamorgan"}
        it = wb["Table1"].iter_rows(values_only=True)
        for r in it:
            if r and r[0] == "Authority":
                break
        n_wal, unmatched_w = 0, []
        for r in it:
            if not r or not r[0] or r[1] is None:
                continue
            name = str(r[0]).strip().lower().replace("&", "and")
            if name in ("wales", "total") or "average" in name:
                continue
            code = wales_by_name.get(name) or wales_by_name.get(alias.get(name, "")) or \
                next((c for n, c in wales_by_name.items() if n.endswith(name) or name.endswith(n)), None)
            if not code:
                unmatched_w.append(r[0])
                continue
            d = float(r[1])
            for b, k in RATIO.items():
                rates.append((code, b, round(d * k, 2)))
            n_wal += 1
        if unmatched_w or n_wal != 22:
            raise LoadError(f"Wales: ghép {n_wal}/22 authority, chưa ghép: {unmatched_w}")

        unknown = sorted({c for c, _, _ in rates if c not in lads})
        if unknown:
            raise LoadError(f"Mã LA trong bảng council tax không có trong geo_area LAD: {unknown[:10]}")
        t = ctx.stage_table("ctax", ["lad_code", "band", "amount"], {"amount": "numeric(10,2)"})
        ctx.copy_rows(t, ["lad_code", "band", "amount"], rates, "COPY mức council tax")
        ctx.check_range("Band D", t, "amount", 900, 4000, where="band = 'D'")
        ctx.sql("thay council_tax_rate năm này", "DELETE FROM mkt_uk.council_tax_rate WHERE financial_year = %s", (fy_db,))
        ctx.sql("INSERT council_tax_rate", f"""
            INSERT INTO mkt_uk.council_tax_rate (lad_code, financial_year, band, parish_code, amount_gbp, release_id)
            SELECT lad_code, %s, band, '', amount, %s FROM {t}""", (fy_db, ctx.release_id))
        avg_d = ctx.scalar(f"SELECT avg(amount) FROM {t} WHERE band='D' AND lad_code LIKE 'E%%'")
        log.info("    Band D trung bình (không trọng số) England: £%.0f", avg_d)

        # ---------- metric Band D theo LAD (tiện cho trang khu vực)
        register_metric(ctx, "uk.ctax.band_d", category="costs", dataset="uk.council_tax", value_type="currency",
                        unit="GBP/year", decimals=0, direction=-1, period_type="financial_year", native_level="lad",
                        scope="uk.ew", name="Council tax Band D (area average incl. parish)")
        mv = mv_stage(ctx, "mv_ctax")
        ctx.sql("metric Band D", f"""INSERT INTO {mv} (level, code, metric_id, period, value_num)
            SELECT 'lad', lad_code, 'uk.ctax.band_d', %s, amount FROM {t} WHERE band = 'D'""", (period,))

        # ---------- VOA CTSOP1.1: số nhà theo band ở mọi cấp
        z = ctx.file(r"ctsop1_1\.zip$")
        with zipfile.ZipFile(z) as zf:
            member = next(n for n in zf.namelist() if n.lower().endswith(".csv") and "ctsop1_1" in n.lower())
            text = io.TextIOWrapper(zf.open(member), encoding="utf-8-sig")
            rows, totals, bad_sum = [], {}, 0
            stock_date = date(int(member.split("_")[-3]), int(member.split("_")[-2]), int(member.split("_")[-1][:2]))
            for r in csv.DictReader(text):
                level = CTSOP_LEVEL.get(r["geography"])
                if not level:
                    continue
                counts = {b: (int(r[f"band_{b.lower()}"]) if r[f"band_{b.lower()}"].isdigit() else None) for b in RATIO}
                total = int(r["all_properties"]) if r["all_properties"].isdigit() else None
                known = sum(v for v in counts.values() if v)
                # VOA làm tròn mọi số tới hàng chục → tổng các band có thể vượt tổng tối đa ~9×5; > 50 là sai thật
                if total and known > total + 50:
                    bad_sum += 1
                if level == "nation":
                    totals[r["ecode"]] = total
                rows.append((level, r["ecode"], "uk.ctax.stock", stock_date, total,
                             json.dumps({b: v for b, v in counts.items() if v is not None})))
        log.info("    CTSOP %s: %s dòng, tổng nhà theo nation %s", stock_date, len(rows), totals)
        if bad_sum:
            raise LoadError(f"CTSOP: {bad_sum} dòng có tổng band > tổng số nhà")
        eng = totals.get("E92000001") or 0
        if not 24_000_000 <= eng <= 28_000_000:
            raise LoadError(f"CTSOP: tổng số nhà England bất thường {eng:,}")
        register_metric(ctx, "uk.ctax.stock", category="costs", dataset="uk.council_tax", value_type="distribution",
                        period_type="snapshot", native_level="lsoa", aggregation="sum", scope="uk.ew",
                        name="Dwellings by council tax band",
                        description="VOA CTSOP1.1; value_num = tổng số nhà, value_json = số nhà theo band (ô '-' = < 5, bị ẩn)")
        ctx.copy_rows(mv, MV_COLS, rows, "COPY CTSOP")
        n_lsoa = ctx.scalar(f"SELECT count(*) FROM {mv} WHERE metric_id='uk.ctax.stock' AND level='lsoa'")
        if n_lsoa < 35000:
            raise LoadError(f"CTSOP: chỉ {n_lsoa} LSOA")
        n, unmatched = insert_values(ctx, mv, "council tax")
        ctx.stats["rate_rows"] = len(rates)
        ctx.drop_stage("ctax", "mv_ctax")
        return {"financial_year": fy, "england_authorities": n_eng, "wales_authorities": n_wal,
                "metric_values": n, "unmatched": unmatched, "stock_date": str(stock_date)}
