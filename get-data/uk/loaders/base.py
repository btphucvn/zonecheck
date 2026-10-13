"""Khung chung cho loader: nạp một release đã tải (uk/data/<source>/<version>/) vào DB.

Mỗi bước SQL được log kèm số dòng và thời gian để dễ lần ra bước lỗi/chậm.
Dữ liệu trung gian nằm ở schema stage_uk (bảng UNLOGGED, xoá sau khi nạp xong).
"""
from __future__ import annotations

import csv
import io
import logging
import re
import subprocess
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import unquote, urlparse

from common.config import database_url

log = logging.getLogger(__name__)

STAGE = "stage_uk"


class LoadError(RuntimeError):
    pass


class Loader:
    """Lớp con khai báo source (trùng tên tool tải) và viết load(ctx) → dict thống kê."""

    source: str = ""
    depends_on: tuple[str, ...] = ()
    description: str = ""

    def load(self, ctx: "LoadContext") -> dict:
        raise NotImplementedError


class LoadContext:
    def __init__(self, conn, manifest: dict, rel_dir: Path):
        self.conn = conn
        self.manifest = manifest
        self.dir = rel_dir
        self.release_id = manifest.get("release_id")
        self.version = manifest["version"]
        self.stats: dict = {}

    # ------------------------------------------------------------- file -----
    def file(self, pattern: str) -> Path:
        """File duy nhất trong release khớp regex."""
        hits = [p for p in sorted(self.dir.iterdir()) if p.is_file() and re.search(pattern, p.name)]
        if len(hits) != 1:
            raise LoadError(f"Cần đúng 1 file khớp {pattern!r} trong {self.dir}, thấy {[p.name for p in hits]}")
        return hits[0]

    def files(self, pattern: str) -> list[Path]:
        return [p for p in sorted(self.dir.iterdir()) if p.is_file() and re.search(pattern, p.name)]

    # -------------------------------------------------------------- SQL -----
    def sql(self, label: str, query: str, params=None) -> int:
        """Chạy một câu SQL, log số dòng ảnh hưởng và thời gian. Lỗi kèm nhãn bước + đoạn SQL."""
        t0 = time.monotonic()
        try:
            cur = self.conn.execute(query, params)
        except Exception as e:
            raise LoadError(f"Bước '{label}' lỗi: {type(e).__name__}: {e}\nSQL: {query.strip()[:1500]}") from e
        n = cur.rowcount
        # bảng tạm/stage vừa tạo bằng CREATE ... AS chưa có thống kê → planner dễ chọn nested loop rất chậm
        m = re.match(r"\s*CREATE\s+(?:TEMP\s+|TEMPORARY\s+|UNLOGGED\s+)?TABLE\s+([\w.]+)", query, re.I)
        if m:
            self.conn.execute(f"ANALYZE {m.group(1)}")
        log.info("    %-45s %10s dòng  %6.1fs", label, f"{n:,}" if n is not None and n >= 0 else "-",
                 time.monotonic() - t0)
        return n

    def scalar(self, query: str, params=None):
        row = self.conn.execute(query, params).fetchone()
        return row[0] if row else None

    def stage_table(self, name: str, columns: list[str], types: dict[str, str] | None = None) -> str:
        """Tạo lại bảng UNLOGGED stage_uk.<name> với các cột text (hoặc kiểu chỉ định)."""
        types = types or {}
        cols = ", ".join(f'"{c}" {types.get(c, "text")}' for c in columns)
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {STAGE}")
        self.conn.execute(f"DROP TABLE IF EXISTS {STAGE}.{name}")
        self.conn.execute(f"CREATE UNLOGGED TABLE {STAGE}.{name} ({cols})")
        return f"{STAGE}.{name}"

    def drop_stage(self, *names: str) -> None:
        for n in names:
            self.conn.execute(f"DROP TABLE IF EXISTS {STAGE}.{n}")

    def copy_rows(self, table: str, columns: list[str], rows: Iterable[Iterable], label: str = "") -> int:
        """COPY các dòng Python (iterable) vào bảng. Giá trị None → NULL."""
        t0 = time.monotonic()
        n = 0
        cols = ", ".join(f'"{c}"' for c in columns)
        with self.conn.cursor() as cur:
            with cur.copy(f"COPY {table} ({cols}) FROM STDIN") as cp:
                for r in rows:
                    cp.write_row(r)
                    n += 1
        if table.startswith(STAGE + "."):
            self.conn.execute(f"ANALYZE {table}")
        log.info("    %-45s %10s dòng  %6.1fs", label or f"COPY {table}", f"{n:,}", time.monotonic() - t0)
        return n

    def copy_csv(self, table: str, stream: io.RawIOBase, columns: list[str] | None = None, header: bool = True,
                 encoding: str = "UTF8", label: str = "", delimiter: str = ",", analyze: bool = True) -> int:
        """COPY nguyên khối CSV (byte stream) vào bảng — nhanh nhất cho file lớn."""
        t0 = time.monotonic()
        cols = f" ({', '.join(chr(34) + c + chr(34) for c in columns)})" if columns else ""
        opts = f"FORMAT csv, HEADER {str(header).lower()}, ENCODING '{encoding}', DELIMITER '{delimiter}'"
        with self.conn.cursor() as cur:
            try:
                with cur.copy(f"COPY {table}{cols} FROM STDIN WITH ({opts})") as cp:
                    while chunk := stream.read(1 << 20):
                        cp.write(chunk)
            except Exception as e:
                raise LoadError(f"COPY vào {table} lỗi ({label}): {type(e).__name__}: {e}") from e
            n = cur.rowcount
        if analyze and table.startswith(STAGE + "."):
            self.conn.execute(f"ANALYZE {table}")
        log.info("    %-45s %10s dòng  %6.1fs", label or f"COPY {table}", f"{n:,}", time.monotonic() - t0)
        return n

    def ogr_load(self, src: str, table: str, extra: list[str] | None = None, layer: str | None = None) -> None:
        """Nạp file không gian (GeoJSON, GeoPackage, ...) vào stage_uk bằng ogr2ogr."""
        self.conn.execute(f"CREATE SCHEMA IF NOT EXISTS {STAGE}")
        cmd = ["ogr2ogr", "-f", "PostgreSQL", f"PG:{pg_dsn()}", src, "-nln", f"{STAGE}.{table}",
               "-overwrite", "-lco", "GEOMETRY_NAME=geom", "-lco", "SPATIAL_INDEX=NONE", "-lco", "UNLOGGED=ON",
               "-nlt", "PROMOTE_TO_MULTI", "-t_srs", "EPSG:4326", "--config", "PG_USE_COPY", "YES",
               *(extra or [])]
        if layer:
            cmd.append(layer)
        t0 = time.monotonic()
        log.debug("    ogr2ogr: %s", " ".join(c if "password" not in c else "PG:<dsn>" for c in cmd))
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise LoadError(f"ogr2ogr lỗi (exit {p.returncode}) khi nạp {src} → {STAGE}.{table}:\n"
                            f"stderr: {p.stderr[-3000:]}\nstdout: {p.stdout[-1000:]}")
        if p.stderr.strip():
            log.warning("    ogr2ogr cảnh báo: %s", p.stderr.strip()[-1500:])
        self.conn.execute(f"ANALYZE {STAGE}.{table}")  # thiếu thống kê → planner chọn nested loop rất chậm
        n = self.scalar(f"SELECT count(*) FROM {STAGE}.{table}")
        log.info("    %-45s %10s dòng  %6.1fs", f"ogr2ogr → {STAGE}.{table}", f"{n:,}", time.monotonic() - t0)

    @contextmanager
    def without_fks(self, table: str):
        """Tạm bỏ khoá ngoại của `table` khi nạp hàng loạt, xong thì thêm lại (Postgres kiểm tra toàn bảng một lần).

        Kiểm tra FK theo từng dòng (trigger) với hàng chục triệu dòng chạy hàng giờ; ADD CONSTRAINT kiểm tra bằng
        một truy vấn join nên nhanh hơn nhiều. Vẫn trong cùng transaction: dữ liệu vi phạm → lỗi → rollback toàn bộ.
        """
        fks = self.conn.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'f'",
            (table,)).fetchall()
        for name, _ in fks:
            self.conn.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"')
        log.info("    tạm bỏ %s khoá ngoại của %s: %s", len(fks), table, [n for n, _ in fks])
        yield
        for name, definition in fks:
            self.sql(f"thêm lại + kiểm tra FK {name}", f'ALTER TABLE {table} ADD CONSTRAINT "{name}" {definition}')

    # ------------------------------------------------------- kiểm tra hợp lý -----
    def check_range(self, label: str, table: str, expr: str, lo: float, hi: float, where: str = "true",
                    max_bad: int = 0) -> None:
        """Mọi giá trị expr (không NULL) phải nằm trong [lo, hi]. Quá max_bad dòng vi phạm → LoadError (rollback)."""
        row = self.conn.execute(
            f"SELECT count(*) FILTER (WHERE ({expr}) < %s OR ({expr}) > %s), count({expr}), min({expr}), max({expr}) "
            f"FROM {table} WHERE {where}", (lo, hi)).fetchone()
        bad, n, mn, mx = row
        self.stats[f"range:{label}"] = {"n": n, "min": mn, "max": mx, "out_of_range": bad}
        if bad > max_bad:
            sample = self.conn.execute(
                f"SELECT {expr} FROM {table} WHERE {where} AND (({expr}) < %s OR ({expr}) > %s) LIMIT 5",
                (lo, hi)).fetchall()
            raise LoadError(f"Kiểm tra khoảng '{label}' thất bại: {bad}/{n} giá trị ngoài [{lo}, {hi}] "
                            f"(min={mn}, max={mx}), ví dụ {[r[0] for r in sample]}")
        log.info("    ✓ khoảng %s: n=%s, min=%s, max=%s trong [%s, %s]%s", label, f"{n:,}", mn, mx, lo, hi,
                 f" ({bad} ngoại lệ cho phép)" if bad else "")

    def check_not_null_ratio(self, label: str, table: str, expr: str, min_ratio: float, where: str = "true") -> None:
        """Tỉ lệ dòng có expr khác NULL phải ≥ min_ratio (phát hiện cột đổi tên/định dạng làm mất dữ liệu)."""
        n, nn = self.conn.execute(f"SELECT count(*), count({expr}) FROM {table} WHERE {where}").fetchone()
        ratio = nn / n if n else 0
        self.stats[f"notnull:{label}"] = round(ratio, 4)
        if ratio < min_ratio:
            raise LoadError(f"Kiểm tra '{label}' thất bại: chỉ {nn:,}/{n:,} ({ratio:.1%}) có giá trị, cần ≥ {min_ratio:.0%}")
        log.info("    ✓ có giá trị %s: %.1f%% (cần ≥ %.0f%%)", label, ratio * 100, min_ratio * 100)

    def check_values_in(self, label: str, table: str, expr: str, allowed: list, where: str = "true") -> None:
        """Mọi giá trị (không NULL) của expr phải thuộc allowed."""
        bad = self.conn.execute(
            f"SELECT {expr}, count(*) FROM {table} WHERE {where} AND {expr} IS NOT NULL AND NOT ({expr} = ANY(%s)) "
            f"GROUP BY 1 ORDER BY 2 DESC LIMIT 10", (allowed,)).fetchall()
        if bad:
            raise LoadError(f"Kiểm tra '{label}' thất bại: giá trị ngoài tập cho phép {bad}")
        log.info("    ✓ giá trị %s thuộc tập cho phép", label)

    def expect(self, label: str, actual: int, expected: int, tolerance: float = 0.0) -> None:
        """Kiểm tra số dòng. Lệch quá tolerance (tỉ lệ) → lỗi, dừng nạp và rollback."""
        self.stats[label] = actual
        if expected == 0 and actual == 0:
            return
        diff = abs(actual - expected) / max(expected, 1)
        if diff > tolerance:
            raise LoadError(f"Kiểm tra '{label}' thất bại: thực tế {actual:,}, kỳ vọng {expected:,} "
                            f"(lệch {diff:.2%} > cho phép {tolerance:.2%})")
        log.info("    ✓ %s: %s (kỳ vọng %s)", label, f"{actual:,}", f"{expected:,}")


def pg_dsn() -> str:
    """DATABASE_URL → chuỗi libpq key=value cho ogr2ogr."""
    u = urlparse(database_url() or "")
    parts = {"host": u.hostname, "port": u.port, "dbname": u.path.lstrip("/"),
             "user": unquote(u.username or ""), "password": unquote(u.password or "")}
    return " ".join(f"{k}={v}" for k, v in parts.items() if v)


def zip_members(path: Path, pattern: str) -> list[str]:
    with zipfile.ZipFile(path) as z:
        return sorted(n for n in z.namelist() if re.search(pattern, n))


def iter_zip_csv(path: Path, member: str, encoding: str = "utf-8", **kw) -> Iterator[dict]:
    with zipfile.ZipFile(path) as z, z.open(member) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding=encoding, newline=""), **kw)


def slug_sql(expr: str) -> str:
    """Biểu thức SQL tạo slug: bỏ dấu, chữ thường, ký tự khác chữ/số → '-'."""
    return (f"trim(both '-' from regexp_replace(lower(public.unaccent(coalesce({expr}, ''))), "
            f"'[^a-z0-9]+', '-', 'g'))")

