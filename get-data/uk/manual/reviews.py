"""Duyệt review cư dân gửi từ web (mkt_uk.review).

    python -m uk.manual.reviews                 # liệt kê review đang chờ (mới nhất trước)
    python -m uk.manual.reviews approve <id>…   # cho hiện trên web
    python -m uk.manual.reviews reject <id>…    # ẩn vĩnh viễn

Web cache review theo giờ: review được duyệt hiện ra trong vòng 1 giờ.
"""
from __future__ import annotations

import sys
import textwrap

from common import db


def main(argv: list[str]) -> int:
    c = db.conn()
    if c is None:
        print("Không kết nối được DB (mở tunnel: ./auth_key/vps/tunnel.sh -f)")
        return 1
    if not argv:
        rows = c.execute("""SELECT id, postcode, overall, title, body, improve, author, relation, created_at::date
                            FROM mkt_uk.review WHERE status = 'pending' ORDER BY created_at DESC LIMIT 50""").fetchall()
        for r in rows:
            print(f"\n{r[0]}  {r[1]}  {r[2]:.1f}/10  {r[6]} ({r[7]}), {r[8]}\n  {r[3]}")
            print(textwrap.indent(textwrap.fill(r[4], 100), "  "))
            if r[5]:
                print(textwrap.indent(textwrap.fill("To improve: " + r[5], 100), "  "))
        print(f"\n{len(rows)} review đang chờ")
        return 0
    action, ids = argv[0], argv[1:]
    if action not in ("approve", "reject") or not ids:
        print(__doc__)
        return 2
    n = c.execute("UPDATE mkt_uk.review SET status = %s, moderated_at = now() WHERE id = ANY(%s::uuid[]) AND status = 'pending'",
                  ("approved" if action == "approve" else "rejected", ids)).rowcount
    print(f"{action}: {n} review")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
