"""Tên đường cho từng postcode → mkt_uk.postcode_street, để ô tìm kiếm gợi ý "Choumert Road, London, SE15 4AA".

1. Từ HM Land Registry Price Paid: với mỗi postcode, cặp (street, town) xuất hiện nhiều giao dịch nhất
   (hoà thì lấy cặp có giao dịch gần nhất).
2. Postcode đang dùng chưa từng có giao dịch: lấy tên đường của postcode gần nhất trong
   NEAREST_MAX_M mét, đánh dấu is_nearest (web hiển thị "gần ...", không khẳng định là địa chỉ).

Bảng được dựng mới rồi hoán đổi ở cuối transaction, nên web chỉ bị khoá trong khoảnh khắc đổi tên.
"""
from __future__ import annotations

import logging

from ..loaders.base import LoadContext, LoadError
from .base import Step

log = logging.getLogger(__name__)

# Postcode → tên đường đã biết (kiểm tra chéo)
KNOWN = {"SE15 4AA": "CHOUMERT ROAD", "SE15 4BD": "CHOUMERT MEWS", "SE15 4AE": "AVONDALE RISE"}
NEAREST_MAX_M = 250
EW = ("E92000001", "W92000004")


class Streets(Step):
    name = "streets"
    needs_sources = ("ppd", "onspd")
    description = "Tên đường + post town cho mỗi postcode (từ Price Paid, thiếu thì lấy postcode gần nhất) → mkt_uk.postcode_street"

    def run(self, ctx: LoadContext) -> dict:
        ctx.conn.execute("DROP TABLE IF EXISTS mkt_uk.postcode_street_new")
        ctx.conn.execute("""
            CREATE TABLE mkt_uk.postcode_street_new (
                postcode text PRIMARY KEY REFERENCES mkt_uk.postcode (postcode),
                street text NOT NULL,
                post_town text,
                sales integer NOT NULL,
                is_nearest boolean NOT NULL DEFAULT false,
                distance_m real
            )""")
        n = ctx.sql("tên đường phổ biến nhất mỗi postcode", """
            INSERT INTO mkt_uk.postcode_street_new (postcode, street, post_town, sales)
            SELECT DISTINCT ON (x.postcode) x.postcode, x.street, x.town, x.n
            FROM (
                SELECT postcode, upper(btrim(street)) AS street, nullif(upper(btrim(town)), '') AS town,
                       count(*) AS n, max(transfer_date) AS last
                FROM mkt_uk.price_paid
                WHERE postcode IS NOT NULL AND nullif(btrim(street), '') IS NOT NULL
                GROUP BY 1, 2, 3
            ) x
            JOIN mkt_uk.postcode p ON p.postcode = x.postcode
            ORDER BY x.postcode, x.n DESC, x.last DESC""")

        ctx.sql("điểm postcode có tên đường", """
            CREATE TEMP TABLE named ON COMMIT DROP AS
            SELECT s.postcode, s.street, s.post_town, p.geom
            FROM mkt_uk.postcode_street_new s JOIN mkt_uk.postcode p USING (postcode)
            WHERE p.geom IS NOT NULL""")
        ctx.conn.execute("CREATE INDEX ON named USING gist (geom)")
        ctx.conn.execute("ANALYZE named")
        # lọc tập thiếu trước, KNN không kèm bộ lọc (lọc district trong KNN quét quá nhiều điểm)
        ctx.sql("postcode đang dùng chưa có tên đường", f"""
            CREATE TEMP TABLE missing ON COMMIT DROP AS
            SELECT p.postcode, p.geom FROM mkt_uk.postcode p
            WHERE p.status = 'live' AND p.geom IS NOT NULL AND p.country_code IN {EW}
              AND NOT EXISTS (SELECT 1 FROM mkt_uk.postcode_street_new s WHERE s.postcode = p.postcode)""")
        near = ctx.sql("postcode thiếu tên → postcode gần nhất", f"""
            INSERT INTO mkt_uk.postcode_street_new (postcode, street, post_town, sales, is_nearest, distance_m)
            SELECT m.postcode, nn.street, nn.post_town, 0, true, nn.d
            FROM missing m
            CROSS JOIN LATERAL (
                SELECT n.street, n.post_town, ST_Distance(n.geom::geography, m.geom::geography) AS d
                FROM named n ORDER BY n.geom <-> m.geom LIMIT 1
            ) nn
            WHERE nn.d <= {NEAREST_MAX_M}""")

        live = ctx.scalar(f"SELECT count(*) FROM mkt_uk.postcode WHERE status = 'live' AND country_code IN {EW}")
        direct = ctx.scalar(f"""SELECT count(*) FROM mkt_uk.postcode_street_new s JOIN mkt_uk.postcode p USING (postcode)
                                WHERE p.status = 'live' AND p.country_code IN {EW} AND NOT s.is_nearest""")
        share, total_share = direct / live, (direct + near) / live
        log.info("    %s postcode có tên đường từ Price Paid, %s lấy từ postcode gần nhất; postcode đang dùng ở E&W: "
                 "%.1f%% trực tiếp, %.1f%% tổng (/%s)", f"{n:,}", f"{near:,}", share * 100, total_share * 100, f"{live:,}")
        # Price Paid phủ hầu hết postcode dân cư; postcode doanh nghiệp/hộp thư thì không → khoảng 60–90%
        if not 0.5 <= share <= 0.95:
            raise LoadError(f"Tỉ lệ postcode E&W có tên đường từ Price Paid bất thường: {share:.1%}")
        if not share < total_share <= 1:
            raise LoadError(f"Tỉ lệ sau khi lấy postcode gần nhất bất thường: {total_share:.1%}")
        for pc, want in KNOWN.items():
            got = ctx.scalar("SELECT street FROM mkt_uk.postcode_street_new WHERE postcode = %s AND NOT is_nearest", (pc,))
            if got != want:
                raise LoadError(f"{pc}: tên đường '{got}', mong đợi '{want}'")

        # Tìm "choumert ro" hoặc "high street harrow": tiền tố của "street post_town"
        ctx.conn.execute("""CREATE INDEX postcode_street_new_trgm ON mkt_uk.postcode_street_new
                            USING gin ((street || ' ' || coalesce(post_town, '')) gin_trgm_ops)""")
        ctx.conn.execute("DROP TABLE IF EXISTS mkt_uk.postcode_street")
        ctx.conn.execute("ALTER TABLE mkt_uk.postcode_street_new RENAME TO postcode_street")
        ctx.conn.execute("ALTER TABLE mkt_uk.postcode_street RENAME CONSTRAINT postcode_street_new_pkey TO postcode_street_pkey")
        ctx.conn.execute("ALTER TABLE mkt_uk.postcode_street RENAME CONSTRAINT postcode_street_new_postcode_fkey TO postcode_street_postcode_fkey")
        ctx.conn.execute("ALTER INDEX mkt_uk.postcode_street_new_trgm RENAME TO postcode_street_trgm")
        ctx.conn.execute("ANALYZE mkt_uk.postcode_street")
        return {"postcodes": n, "nearest": near, "live_ew_total": live, "share_direct": round(share, 4),
                "share_total": round(total_share, 4)}
