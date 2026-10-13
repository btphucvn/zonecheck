"""Nạp EPC nhà ở (bulk CSV theo năm trong zip ~8 GB / ~50 GB giải nén) → mkt_uk.epc_certificate.

- Không lưu địa chỉ đầy đủ (quyền Royal Mail/OS): chỉ address_key chuẩn hoá để ghép với Price Paid.
- Mỗi file năm: COPY vào stage đủ cột → trích cột cần sang stage "slim" → xoá stage năm đó (tiết kiệm đĩa).
- is_latest_for_address tính một lần khi INSERT (window theo UPRN, thiếu UPRN thì theo address_key).
"""
from __future__ import annotations

import io
import logging
import re
import zipfile

from .base import LoadContext, LoadError, Loader

log = logging.getLogger(__name__)

NEEDED = ["certificate_number", "address1", "address2", "postcode", "lodgement_date", "inspection_date",
          "current_energy_rating", "potential_energy_rating", "current_energy_efficiency", "property_type",
          "built_form", "construction_age_band", "total_floor_area", "number_habitable_rooms", "main_fuel",
          "mainheat_description", "tenure", "transaction_type", "uprn"]
SLIM = ["certificate_number", "uprn", "postcode", "address_key", "lodgement_date", "inspection_date",
        "current_rating", "potential_rating", "current_efficiency", "property_type", "built_form",
        "construction_age_band", "total_floor_area", "habitable_rooms", "main_fuel", "main_heating", "tenure",
        "transaction_type"]
EPC_INDEXES = {
    "epc_uprn": "CREATE INDEX epc_uprn ON mkt_uk.epc_certificate (uprn) WHERE uprn IS NOT NULL",
    "epc_postcode_latest": "CREATE INDEX epc_postcode_latest ON mkt_uk.epc_certificate (postcode) WHERE is_latest_for_address",
    "epc_address_key": "CREATE INDEX epc_address_key ON mkt_uk.epc_certificate (address_key)",
}


class EpcLoader(Loader):
    source = "epc"
    depends_on = ("onspd",)
    description = "EPC domestic (mọi năm) → mkt_uk.epc_certificate (thay toàn bộ), kiểm tra hạng/diện tích/trùng"

    def load(self, ctx: LoadContext) -> dict:
        z = ctx.file(r"\.zip$")
        with zipfile.ZipFile(z) as zf:
            members = sorted(n for n in zf.namelist() if re.fullmatch(r"certificates-\d{4}\.csv", n.split("/")[-1]))
        if len(members) < 10:
            raise LoadError(f"Zip EPC chỉ có {len(members)} file certificates-YYYY.csv")
        slim = ctx.stage_table("epc_slim", SLIM)
        per_year = {}
        for m in members:
            year = re.search(r"(\d{4})", m.split("/")[-1]).group(1)
            with zipfile.ZipFile(z) as zf, zf.open(m) as f:
                header = f.readline().decode("utf-8-sig").strip().split(",")
                missing = [c for c in NEEDED if c not in header]
                if missing:
                    raise LoadError(f"{m}: thiếu cột {missing}")
                raw = ctx.stage_table("epc_raw", header)
                n = ctx.copy_csv(raw, io.BufferedReader(f), header=False, analyze=False, label=f"COPY {m}")
            # address_key: chuẩn hoá (chữ hoa, bỏ dấu câu, gộp khoảng trắng) địa chỉ dòng 1–2 + postcode → chỉ để ghép
            moved = ctx.sql(f"trích cột {year}", f"""
                INSERT INTO {slim}
                SELECT certificate_number, nullif(uprn, ''), nullif(upper(trim(postcode)), ''),
                       regexp_replace(upper(concat_ws(' ', address1, address2)), '[^A-Z0-9]+', ' ', 'g')
                           || '|' || upper(replace(postcode, ' ', '')),
                       nullif(lodgement_date, ''), nullif(inspection_date, ''),
                       nullif(current_energy_rating, ''), nullif(potential_energy_rating, ''),
                       nullif(current_energy_efficiency, ''), nullif(property_type, ''), nullif(built_form, ''),
                       nullif(construction_age_band, ''), nullif(total_floor_area, ''),
                       nullif(number_habitable_rooms, ''), nullif(main_fuel, ''), nullif(mainheat_description, ''),
                       nullif(tenure, ''), nullif(transaction_type, '')
                FROM {raw}""")
            if moved != n:
                raise LoadError(f"{m}: COPY {n} dòng nhưng trích được {moved}")
            per_year[year] = n
            ctx.drop_stage("epc_raw")
        total = sum(per_year.values())
        log.info("    chứng chỉ theo năm: %s; tổng %s", per_year, f"{total:,}")
        ctx.conn.execute(f"ANALYZE {slim}")

        # ---------- kiểm tra hợp lý trên stage (trước khi đụng bảng thật)
        dup = ctx.scalar(f"SELECT count(*) - count(DISTINCT certificate_number) FROM {slim}")
        if dup > total * 0.001:
            raise LoadError(f"{dup:,} mã chứng chỉ trùng (> 0,1%)")
        ctx.check_values_in("hạng hiện tại", slim, "current_rating", list("ABCDEFG"))
        ctx.check_not_null_ratio("hạng hiện tại", slim, "current_rating", 0.98)
        ctx.check_not_null_ratio("postcode", slim, "postcode", 0.99)
        ctx.check_not_null_ratio("diện tích sàn", slim, "total_floor_area", 0.95)
        bad_area = ctx.scalar(f"""SELECT count(*) FROM {slim} WHERE total_floor_area !~ '^[0-9.]+$'
                                  OR total_floor_area::numeric NOT BETWEEN 5 AND 2000""")
        log.info("    diện tích sàn ngoài 5–2000 m² hoặc không phải số → để NULL: %s (%.3f%%)",
                 f"{bad_area:,}", bad_area * 100 / total)
        if bad_area > total * 0.01:
            raise LoadError(f"{bad_area:,} chứng chỉ có diện tích bất thường (> 1%)")
        dist = dict(ctx.conn.execute(f"SELECT current_rating, round(100.0 * count(*) / sum(count(*)) OVER (), 1) "
                                     f"FROM {slim} GROUP BY 1 ORDER BY 1").fetchall())
        log.info("    phân bố hạng (mọi chứng chỉ): %s", dist)
        # Thống kê công bố: hạng D phổ biến nhất (~35–45%), A rất hiếm (< 2%)
        if not (25 <= (dist.get("D") or 0) <= 55 and (dist.get("A") or 0) < 3):
            raise LoadError(f"Phân bố hạng EPC bất thường: {dist}")

        # ---------- thay toàn bộ bảng
        for name in EPC_INDEXES:
            ctx.conn.execute(f"DROP INDEX IF EXISTS mkt_uk.{name}")
        ctx.sql("TRUNCATE epc_certificate (+ ppd_epc_match)", "TRUNCATE mkt_uk.epc_certificate CASCADE")
        with ctx.without_fks("mkt_uk.epc_certificate"):
            ctx.conn.execute("SET LOCAL enable_nestloop = off")
            ctx.sql("INSERT epc_certificate", f"""
                INSERT INTO mkt_uk.epc_certificate (lmk_key, uprn, postcode, address_key, lodgement_date,
                    inspection_date, current_rating, potential_rating, current_efficiency, property_type, built_form,
                    construction_age_band, total_floor_area_m2, habitable_rooms, main_fuel, main_heating, tenure,
                    transaction_type, is_latest_for_address, area_id, release_id)
                SELECT DISTINCT ON (s.certificate_number)
                       s.certificate_number,
                       CASE WHEN s.uprn ~ '^[0-9]{{1,12}}$' THEN s.uprn::bigint END, s.postcode, s.address_key,
                       s.lodgement_date::date, CASE WHEN s.inspection_date ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' THEN s.inspection_date::date END,
                       s.current_rating,
                       CASE WHEN s.potential_rating ~ '^[A-G]$' THEN s.potential_rating END,
                       CASE WHEN s.current_efficiency ~ '^-?[0-9]{{1,3}}$' THEN s.current_efficiency::smallint END,
                       s.property_type, s.built_form, s.construction_age_band,
                       CASE WHEN s.total_floor_area ~ '^[0-9.]+$' AND s.total_floor_area::numeric BETWEEN 5 AND 2000
                            THEN s.total_floor_area::numeric(8, 2) END,
                       CASE WHEN s.habitable_rooms ~ '^[0-9]{{1,2}}$' THEN s.habitable_rooms::smallint END,
                       s.main_fuel, s.main_heating, s.tenure, s.transaction_type,
                       s.rn = 1, pc.area_id, %s
                FROM (SELECT *, row_number() OVER (
                          PARTITION BY coalesce(CASE WHEN uprn ~ '^[0-9]{{1,12}}$' THEN 'U' || uprn END, 'A' || address_key)
                          ORDER BY lodgement_date DESC, certificate_number DESC) AS rn
                      FROM {slim}) s
                LEFT JOIN mkt_uk.postcode pc ON pc.postcode = s.postcode
                ORDER BY s.certificate_number, s.lodgement_date DESC""", (ctx.release_id,))
            for name, ddl in EPC_INDEXES.items():
                ctx.sql(f"index {name}", ddl)
        n_db = ctx.scalar("SELECT count(*) FROM mkt_uk.epc_certificate")
        ctx.expect("mkt_uk.epc_certificate", n_db, total - dup)
        latest = ctx.scalar("SELECT count(*) FROM mkt_uk.epc_certificate WHERE is_latest_for_address")
        no_area = ctx.scalar("SELECT count(*) FROM mkt_uk.epc_certificate WHERE area_id IS NULL")
        log.info("    nhà (chứng chỉ mới nhất): %s; chứng chỉ không ghép được postcode: %s (%.2f%%)",
                 f"{latest:,}", f"{no_area:,}", no_area * 100 / n_db)
        if not 15_000_000 <= latest <= 35_000_000:
            raise LoadError(f"Số nhà có EPC bất thường: {latest:,} (E&W có ~25 triệu nhà)")
        if no_area > n_db * 0.03:
            raise LoadError(f"{no_area:,} chứng chỉ không ghép được postcode (> 3%)")
        ctx.conn.execute("ANALYZE mkt_uk.epc_certificate")
        ctx.drop_stage("epc_slim")
        return {"certificates": n_db, "properties_latest": latest, "duplicates_removed": dup, "per_year": per_year,
                "rating_distribution": dist}
