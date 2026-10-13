"""Đọc file ODS rất lớn theo kiểu streaming (pandas/odfpy nạp cả cây XML vào RAM → treo với file > 1 GB).

    for row in iter_ods_rows(path, "Sheet1"):
        ...  # row là list giá trị (float cho ô số, str cho ô chữ, None cho ô trống)
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Iterator
from xml.etree.ElementTree import iterparse

NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
T = "{%s}" % NS["table"]
O = "{%s}" % NS["office"]
TX = "{%s}" % NS["text"]
MAX_REPEAT = 1000  # ô trống lặp hàng nghìn lần ở cuối dòng/bảng → cắt bớt


def sheet_names(path: Path) -> list[str]:
    names = []
    with zipfile.ZipFile(path) as z, z.open("content.xml") as f:
        for ev, el in iterparse(f, events=("start",)):
            if el.tag == T + "table":
                names.append(el.get(T + "name"))
            elif el.tag == T + "table-row":
                pass
    return names


def _cell_value(cell):
    vtype = cell.get(O + "value-type")
    if vtype in ("float", "percentage", "currency"):
        return float(cell.get(O + "value"))
    if vtype == "date":
        return cell.get(O + "date-value")
    if vtype == "boolean":
        return cell.get(O + "boolean-value") == "true"
    texts = ["".join(p.itertext()) for p in cell.iter(TX + "p")]
    return "\n".join(texts) if texts else None


def iter_ods_rows(path: Path, sheet: str) -> Iterator[list]:
    """Sinh từng dòng của sheet. Bỏ các dòng trống lặp ở cuối bảng."""
    in_sheet = False
    with zipfile.ZipFile(path) as z, z.open("content.xml") as f:
        for ev, el in iterparse(f, events=("start", "end")):
            if el.tag == T + "table":
                if ev == "start":
                    in_sheet = el.get(T + "name") == sheet
                elif in_sheet:
                    return
                continue
            if not in_sheet or ev != "end" or el.tag != T + "table-row":
                if ev == "end" and el.tag == T + "table-row":
                    el.clear()
                continue
            row = []
            for cell in el:
                if cell.tag not in (T + "table-cell", T + "covered-table-cell"):
                    continue
                rep = min(int(cell.get(T + "number-columns-repeated", "1")), MAX_REPEAT)
                row.extend([_cell_value(cell)] * rep)
            while row and row[-1] is None:
                row.pop()
            rrep = int(el.get(T + "number-rows-repeated", "1"))
            el.clear()
            if not row:
                continue  # dòng trống (thường lặp hàng triệu lần ở cuối)
            for _ in range(min(rrep, MAX_REPEAT)):
                yield row
