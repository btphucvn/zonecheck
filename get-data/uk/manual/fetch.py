"""Tải các nguồn chặn client tự động (Cloudflare) bằng Chrome thật qua Playwright. Chạy ở MÁY LOCAL (cần màn hình).

    pip install playwright              # dùng Chrome đã cài, không cần `playwright install`
    python3 get-data/uk/manual/fetch.py [ofcom] [nhs]

- Ofcom Connected Nations: tìm bản mới nhất (báo cáo năm hoặc bản cập nhật Spring/Summer) có
  fixed_broadband_coverage + mobile_coverage → uk/manual/ofcom/
- NHS England: tháng mới nhất đã công bố của "Patients Registered at a GP Practice" → file totals
  → uk/manual/nhs_gp_patients/gp-reg-pat-prac-all-YYYY-MM.zip

File đã có thì bỏ qua. Xong thì rsync uk/manual/ lên VPS và chạy `python -m uk ofcom_connected_nations nhs_gp_patients`.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PROFILE = HERE / ".chrome-profile"  # giữ cookie Cloudflare giữa các lần chạy (không commit)
OFCOM = "https://www.ofcom.org.uk"
OFCOM_INDEX = f"{OFCOM}/phones-and-broadband/coverage-and-speeds"
OFCOM_KINDS = {"fixed": r"(\d{6})_fixed_broadband_coverage[^/]*\.zip", "mobile": r"(\d{6})_mobile_coverage[^/]*\.zip"}
NHS_INDEX = "https://digital.nhs.uk/data-and-information/publications/statistical/patients-registered-at-a-gp-practice"


def open_page(pg, url: str) -> None:
    pg.goto(url, wait_until="domcontentloaded", timeout=90_000)
    for _ in range(30):  # trang chờ Cloudflare "Just a moment..."
        if "Just a moment" not in pg.title():
            break
        time.sleep(2)
    time.sleep(2)
    if "Just a moment" in pg.title():
        raise RuntimeError(f"Kẹt ở trang kiểm tra Cloudflare: {url}")


def links(pg) -> list[tuple[str, str]]:
    for attempt in range(5):  # trang có thể còn chuyển hướng (Cloudflare, ngôn ngữ) sau domcontentloaded
        try:
            pg.wait_for_load_state("load", timeout=30_000)
            return pg.eval_on_selector_all("a[href]", "els => els.map(e => [e.innerText.trim(), e.href])")
        except Exception as e:  # noqa: BLE001
            if "context was destroyed" not in str(e) or attempt == 4:
                raise
            time.sleep(2)


def save(pg, url: str, dest: Path) -> None:
    if dest.exists():
        print(f"  đã có {dest.name}, bỏ qua")
        return
    with pg.expect_download(timeout=900_000) as d:
        pg.evaluate("u => { const a = document.createElement('a'); a.href = u; a.download = '';"
                    " document.body.appendChild(a); a.click(); }", url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    d.value.save_as(tmp)
    if tmp.stat().st_size < 1000:
        raise RuntimeError(f"File tải về quá nhỏ ({tmp.stat().st_size} byte), có thể là trang lỗi: {url}")
    tmp.rename(dest)
    print(f"  ✓ {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")


def fetch_ofcom(pg) -> None:
    out = HERE / "ofcom"
    out.mkdir(exist_ok=True)
    open_page(pg, OFCOM_INDEX)
    pages = {h.split("?")[0] for t, h in links(pg) if re.search(r"/connected-nations-(update|20\d\d)", h)}
    open_page(pg, f"{OFCOM_INDEX}/infrastructure-research")
    pages |= {h.split("?")[0] for t, h in links(pg) if re.search(r"/connected-nations-(update|20\d\d)", h)}
    # trang báo cáo năm chỉ trỏ tới trang "data downloads" riêng → thêm các trang đó
    found: dict[str, tuple[str, str]] = {}
    seen = set()
    queue = sorted(pages, reverse=True)
    while queue:
        url = queue.pop(0)
        if url in seen or len(seen) > 12:
            continue
        seen.add(url)
        open_page(pg, url)
        for _, h in links(pg):
            if re.search(r"data-downloads", h) and h.split("?")[0] not in seen:
                queue.append(h.split("?")[0])
            for kind, pat in OFCOM_KINDS.items():
                m = re.search(pat, h)
                if m and (kind not in found or m.group(1) > found[kind][0]):
                    found[kind] = (m.group(1), h)
    missing = set(OFCOM_KINDS) - set(found)
    if missing:
        raise RuntimeError(f"Không tìm thấy file Ofcom {missing} trong các trang {sorted(seen)}")
    for kind, (yyyymm, url) in found.items():
        print(f"Ofcom {kind}: bản {yyyymm} ← {url}")
        save(pg, url, out / re.search(r"[^/]+\.zip", url).group(0))


def fetch_nhs(pg) -> None:
    out = HERE / "nhs_gp_patients"
    out.mkdir(exist_ok=True)
    open_page(pg, NHS_INDEX)
    months = []
    for t, h in links(pg):
        m = re.search(r"Patients Registered at a GP Practice, (\w+ \d{4})", t)
        if m:
            try:
                months.append((datetime.strptime(m.group(1), "%B %Y"), h))
            except ValueError:
                pass
    # danh sách có cả tháng sắp công bố (chưa có file) → thử từ mới đến cũ
    for when, url in sorted(months, reverse=True):
        if when > datetime.now():
            continue
        open_page(pg, url)
        zips = [h for t, h in links(pg) if h.endswith("gp-reg-pat-prac-all.zip")]
        if zips:
            print(f"NHS GP patients: {when:%Y-%m} ← {zips[0]}")
            save(pg, zips[0], out / f"gp-reg-pat-prac-all-{when:%Y-%m}.zip")
            return
        print(f"  {when:%Y-%m}: chưa có file")
    raise RuntimeError("Không tìm thấy file gp-reg-pat-prac-all.zip ở tháng nào")


def main(argv: list[str]) -> int:
    todo = argv or ["ofcom", "nhs"]
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), channel="chrome", headless=False, accept_downloads=True,
                                                   args=["--disable-blink-features=AutomationControlled"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for name in todo:
                {"ofcom": fetch_ofcom, "nhs": fetch_nhs}[name](pg)
        finally:
            ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
