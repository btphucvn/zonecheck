"""Helper dùng lại cho các loại cổng dữ liệu phổ biến ở UK."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from .http import get_json

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- gov.uk -----
def govuk_attachments(path: str) -> list[dict]:
    """Danh sách file đính kèm của một trang gov.uk qua Content API.

    path ví dụ: /government/statistics/english-indices-of-deprivation-2025
    Mỗi phần tử có url, title, content_type, filename...
    """
    d = get_json(f"https://www.gov.uk/api/content{path}")
    atts = d.get("details", {}).get("attachments", [])
    return [a for a in atts if str(a.get("url", "")).startswith("https://assets.publishing.service.gov.uk/")]


def filename_from_url(url: str) -> str:
    return url.split("?")[0].rstrip("/").split("/")[-1]


# ------------------------------------------------------------------- ONS -----
def ons_latest_version(dataset_page: str) -> dict:
    """Bản mới nhất của một dataset trên ons.gov.uk (trang /datasets/...).

    Trả về {"version", "uri", "release_date", "files": [url,...]}.
    """
    page = get_json(f"https://www.ons.gov.uk{dataset_page}/data")
    versions = page.get("datasets") or []
    if not versions:
        raise RuntimeError(f"Không thấy phiên bản nào ở {dataset_page}")
    uri = versions[0]["uri"]
    v = get_json(f"https://www.ons.gov.uk{uri}/data")
    files = [f"https://www.ons.gov.uk/file?uri={uri}/{d['file']}" for d in v.get("downloads", [])]
    files += [f"https://www.ons.gov.uk/file?uri={uri}/{d['file']}" for d in v.get("supplementaryFiles", []) if d.get("file")]
    return {
        "version": uri.rstrip("/").split("/")[-1],
        "uri": uri,
        "release_date": (v.get("description") or {}).get("releaseDate") or page["description"].get("releaseDate"),
        "files": files,
    }


# ---------------------------------------------------------------- ArcGIS -----
ONS_GEO_OWNER = "ONSGeography_data"


def arcgis_search(query: str, item_type: str | None = None, owner: str | None = ONS_GEO_OWNER,
                  num: int = 20) -> list[dict]:
    q = query
    if item_type:
        q += f' AND type:"{item_type}"'
    if owner:
        q += f" AND owner:{owner}"
    d = get_json(
        "https://www.arcgis.com/sharing/rest/search",
        params={"f": "json", "q": q, "num": num, "sortField": "modified", "sortOrder": "desc"},
    )
    return d.get("results", [])


def arcgis_item_data_url(item_id: str) -> str:
    return f"https://www.arcgis.com/sharing/rest/content/items/{item_id}/data"


def arcgis_export_geojson(layer_url: str, dest: Path, out_fields: str = "*", page_size: int = 1000,
                          where: str = "1=1", workers: int = 1, extra: dict | None = None) -> int:
    """Xuất toàn bộ một layer FeatureServer ra file GeoJSON (EPSG:4326).

    Phân trang theo khoảng OBJECTID (keyset), KHÔNG theo resultOffset: khi một trang chạm giới hạn dung lượng,
    ArcGIS trả ít bản ghi hơn yêu cầu (exceededTransferLimit) → phân trang theo offset sẽ bỏ sót bản ghi.
    workers > 1: chia dải OBJECTID thành nhiều khúc, tải song song; mỗi khúc lặp "OBJECTID > id cuối" tới khi hết.
    extra: tham số query bổ sung, ví dụ {"geometryPrecision": 5}.
    Trả về số feature; lệch so với returnCountOnly → lỗi.
    """
    from concurrent.futures import ThreadPoolExecutor

    meta = get_json(layer_url, params={"f": "json"})
    oid = meta.get("objectIdField") or "OBJECTID"
    page_size = min(page_size, int(meta.get("maxRecordCount") or page_size))
    total = get_json(f"{layer_url}/query", params={"f": "json", "where": where, "returnCountOnly": "true"})["count"]
    stats = get_json(f"{layer_url}/query", params={
        "f": "json", "where": where, "outStatistics": json.dumps([
            {"statisticType": "min", "onStatisticField": oid, "outStatisticFieldName": "mn"},
            {"statisticType": "max", "onStatisticField": oid, "outStatisticFieldName": "mx"}])})
    attrs = stats["features"][0]["attributes"]
    lo, hi = int(attrs.get("mn") or attrs.get("MN")), int(attrs.get("mx") or attrs.get("MX"))
    n_chunks = max(1, min(workers * 8, -(-total // page_size)))
    step = -(-(hi - lo + 1) // n_chunks)
    chunks = [(a, min(a + step, hi + 1)) for a in range(lo, hi + 1, step)]
    log.info("  %s: %s feature, OBJECTID %s–%s, %s khúc, %s luồng", layer_url.split("/services/")[-1],
             f"{total:,}", lo, hi, len(chunks), workers)

    def query(params: dict, what: str) -> dict:
        """GET có thử lại. ArcGIS quá tải đôi khi trả HTTP 200 kèm {"error": ...} → phải coi là lỗi, không phải 'hết'."""
        import time
        for attempt in range(8):
            try:
                d = get_json(f"{layer_url}/query", params=params, timeout=600)
                if "error" in d:
                    raise RuntimeError(f"ArcGIS error: {d['error']}")
                return d
            except Exception as e:
                if attempt == 7:
                    raise RuntimeError(f"{what} của {layer_url} lỗi sau 8 lần: {e}") from e
                # 429 = vượt hạn mức "large geometry" (60 yêu cầu/phút): server yêu cầu chờ 60 giây
                wait = 65 if "429" in str(e) else 5 * (attempt + 1)
                log.warning("    %s lỗi (%s), thử lại sau %ss", what, str(e)[:200], wait)
                time.sleep(wait)

    def fetch_once(a: int, b: int) -> list:
        out, last = [], a - 1
        while True:
            params = {"f": "geojson", "outFields": out_fields, "outSR": 4326, "orderByFields": oid,
                      "where": f"({where}) AND {oid} > {last} AND {oid} < {b}",
                      "resultRecordCount": page_size, "returnGeometry": "true", **(extra or {})}
            feats = query(params, f"khúc {a}–{b} sau {last}").get("features", [])
            if not feats:
                return out
            ids = [ft.get("id") if ft.get("id") is not None else (ft.get("properties") or {}).get(oid) for ft in feats]
            if any(i is None for i in ids):
                raise RuntimeError(f"Feature không có {oid} — không phân trang keyset được ({layer_url})")
            out.extend(feats)
            last = max(int(i) for i in ids)

    def fetch(chunk: tuple[int, int]) -> list:
        a, b = chunk
        expected = query({"f": "json", "where": f"({where}) AND {oid} >= {a} AND {oid} < {b}",
                          "returnCountOnly": "true"}, f"đếm khúc {a}–{b}")["count"]
        for attempt in range(3):
            out = fetch_once(a, b)
            if len(out) == expected:
                return out
            log.warning("    khúc %s–%s nhận %s/%s feature, tải lại khúc", a, b, len(out), expected)
        raise RuntimeError(f"Khúc OBJECTID {a}–{b}: nhận {len(out)}/{expected} sau 3 lần ({layer_url})")

    written, done = 0, 0
    tmp = dest.with_name(dest.name + ".part")
    with open(tmp, "w") as f, ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        f.write('{"type":"FeatureCollection","features":[\n')
        for feats in pool.map(fetch, chunks):  # map giữ thứ tự khúc
            for feat in feats:
                f.write(("," if written else "") + json.dumps(feat, separators=(",", ":")) + "\n")
                written += 1
            done += 1
            if done % 8 == 0:
                log.info("    %s/%s khúc, %s feature", done, len(chunks), f"{written:,}")
        f.write("]}\n")
    if written != total:
        raise RuntimeError(f"Xuất thiếu/thừa feature: {written}/{total} ({layer_url})")
    tmp.replace(dest)
    return written


# -------------------------------------------------- OS Downloads API (OGL) -----
def os_product_downloads(product: str, area: str = "GB", fmt: str | None = None) -> tuple[dict, list[dict]]:
    """Thông tin sản phẩm OS OpenData + danh sách file tải (url, fileName, size, md5)."""
    info = get_json(f"https://api.os.uk/downloads/v1/products/{product}")
    files = get_json(f"https://api.os.uk/downloads/v1/products/{product}/downloads")
    files = [x for x in files if x.get("area") == area and (fmt is None or x.get("format") == fmt)]
    return info, files


# ---------------------------------------------------------------- tiện ích -----
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_day_month_year(text: str) -> datetime | None:
    """Tìm ngày dạng '31 August 2026' / '31 Aug 2026' trong chuỗi."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", text)
    if not m or m.group(2)[:3].lower() not in MONTHS:
        return None
    return datetime(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))


def parse_month_year(text: str) -> datetime | None:
    """Tìm 'August 2026' trong chuỗi."""
    m = re.search(r"([A-Za-z]{3,9})\s+(\d{4})", text)
    if not m or m.group(1)[:3].lower() not in MONTHS:
        return None
    return datetime(int(m.group(2)), MONTHS[m.group(1)[:3].lower()], 1)
