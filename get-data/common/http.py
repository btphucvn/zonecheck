"""HTTP: session có retry, tải file lớn có resume (.part + Range) và tính sha256 khi tải."""
from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import USER_AGENT

log = logging.getLogger(__name__)

CHUNK = 1024 * 1024


def session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        respect_retry_after_header=True,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
    s.mount("http://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
    s.headers["User-Agent"] = USER_AGENT
    return s


SESSION = session()

# Một số trang gov (DfE, gov.wales) chặn User-Agent dạng bot → dùng UA trình duyệt cho riêng các nguồn đó
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
}


class HttpError(requests.HTTPError):
    """Lỗi HTTP có đủ ngữ cảnh để debug: method, URL (kể cả sau redirect), status, header, đoạn body."""


def check(r: requests.Response) -> requests.Response:
    if r.status_code < 400:
        return r
    try:
        body = r.text[:5000]
        if "html" in r.headers.get("Content-Type", ""):  # trang lỗi HTML: bỏ script/style/tag, giữ chữ
            body = re.sub(r"(?is)<(script|style)\b.*?</\1>|<!--.*?-->|<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body).strip()[:400]
    except Exception:
        body = "<không đọc được body>"
    hdrs = {k: v for k, v in r.headers.items()
            if k.lower() in ("content-type", "content-length", "retry-after", "server", "cf-ray", "x-cache", "location")}
    redirects = " -> ".join(h.url for h in r.history) if r.history else ""
    msg = (f"HTTP {r.status_code} {r.reason} | {r.request.method} {r.url}"
           + (f" | redirect: {redirects}" if redirects else "")
           + f" | headers={hdrs} | body={body!r}")
    raise HttpError(msg, response=r)


def _get(url: str, **kwargs) -> requests.Response:
    timeout = kwargs.pop("timeout", 120)
    log.debug("GET %s params=%s", url, kwargs.get("params"))
    try:
        r = SESSION.get(url, timeout=timeout, **kwargs)
    except requests.RequestException as e:
        raise requests.ConnectionError(f"GET {url} params={kwargs.get('params')} thất bại: {type(e).__name__}: {e}") from e
    log.debug("  -> %s %s (%s bytes)", r.status_code, r.headers.get("Content-Type"), r.headers.get("Content-Length"))
    return check(r)


def get_json(url: str, **kwargs):
    r = _get(url, **kwargs)
    try:
        return r.json()
    except ValueError as e:
        raise ValueError(f"Phản hồi không phải JSON từ {r.url} (Content-Type={r.headers.get('Content-Type')}): "
                         f"{r.text[:500]!r}") from e


def get_text(url: str, **kwargs) -> str:
    return _get(url, **kwargs).text


def probe(url: str, headers: dict | None = None) -> int:
    """GET byte đầu tiên để kiểm tra file có tồn tại không. Trả về status code (không raise)."""
    try:
        r = SESSION.get(url, headers={"Range": "bytes=0-0", **(headers or {})}, timeout=60, stream=True)
        r.close()
        log.debug("probe %s -> %s", url, r.status_code)
        return r.status_code
    except requests.RequestException as e:
        log.warning("probe %s lỗi mạng: %s: %s", url, type(e).__name__, e)
        return 0


def head(url: str, **kwargs) -> requests.Response:
    log.debug("HEAD %s", url)
    return check(SESSION.head(url, timeout=60, allow_redirects=True, **kwargs))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, headers: dict | None = None, attempts: int = 5) -> dict:
    """Tải url về dest. Ghi vào dest.part rồi đổi tên khi xong; tự resume nếu server hỗ trợ Range.

    Trả về {"path", "url", "bytes", "sha256"}.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, attempts + 1):
        offset = part.stat().st_size if part.exists() else 0
        req_headers = dict(headers or {})
        if offset:
            req_headers["Range"] = f"bytes={offset}-"
        try:
            with SESSION.get(url, headers=req_headers, stream=True, timeout=(30, 300)) as r:
                if r.status_code == 416:  # đã tải đủ
                    log.debug("  %s: 416 với offset %s → coi như đã tải đủ", dest.name, offset)
                    break
                check(r)
                if offset and r.status_code != 206:
                    offset = 0  # server không hỗ trợ Range → tải lại từ đầu
                total = r.headers.get("Content-Length")
                total = int(total) + offset if total else None
                mode = "ab" if offset else "wb"
                done, last_log = offset, time.monotonic()
                with open(part, mode) as f:
                    for chunk in r.iter_content(CHUNK):
                        f.write(chunk)
                        done += len(chunk)
                        if time.monotonic() - last_log > 15:
                            pct = f" ({done * 100 / total:.0f}%)" if total else ""
                            log.info("  %s: %.0f MB%s", dest.name, done / CHUNK, pct)
                            last_log = time.monotonic()
                if total and done < total:
                    raise IOError(f"tải thiếu {done}/{total} bytes")
            break
        except HttpError as e:
            # 4xx (trừ 408/429) là lỗi cố định → không thử lại vô ích
            code = e.response.status_code if e.response is not None else 0
            if 400 <= code < 500 and code not in (408, 429) or attempt == attempts:
                log.error("  tải %s thất bại (lần %s/%s): %s", dest.name, attempt, attempts, e)
                raise
            log.warning("  lỗi tải %s (lần %s/%s): %s", dest.name, attempt, attempts, e)
            time.sleep(10 * attempt)
        except (requests.RequestException, IOError) as e:
            part_size = part.stat().st_size if part.exists() else 0
            detail = f"{type(e).__name__}: {e} | url={url} | đã có {part_size} bytes trong {part.name}"
            if attempt == attempts:
                log.error("  tải %s thất bại sau %s lần: %s", dest.name, attempts, detail)
                raise IOError(f"Tải {url} thất bại sau {attempts} lần: {detail}") from e
            wait = 10 * attempt
            log.warning("  lỗi tải %s (lần %s/%s), thử lại sau %ss: %s", dest.name, attempt, attempts, wait, detail)
            time.sleep(wait)
    # trang đăng nhập / trang lỗi trả HTTP 200 (ví dụ CEDA chuyển sang Keycloak) → không coi là dữ liệu
    if dest.suffix.lower() not in (".html", ".htm", ".xml"):
        with open(part, "rb") as f:
            head_bytes = f.read(512).lstrip().lower()
        if head_bytes.startswith((b"<!doctype html", b"<html")):
            part.unlink()
            raise HttpError(f"{url} trả về trang HTML thay vì file dữ liệu (cần đăng nhập hoặc link đổi?)")
    part.replace(dest)
    log.debug("  đã lưu %s (%s bytes)", dest, dest.stat().st_size)
    return {"path": dest.name, "url": url, "bytes": dest.stat().st_size, "sha256": sha256_file(dest)}
