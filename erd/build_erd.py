#!/usr/bin/env python3
"""Sinh erd/index.html (sơ đồ ERD + tài liệu bảng/cột) từ erd/schema.sql.

Chạy:  python3 erd/build_erd.py
Không cần thư viện ngoài. Script đọc theo quy ước viết trong đầu schema.sql:
  - "-- @domain <key> | <Tiêu đề> | <mô tả>" mở một nhóm bảng
  - CREATE TABLE ... ( mỗi cột một dòng ... ) với ")" đóng ở đầu dòng
  - COMMENT ON SCHEMA/TABLE/COLUMN/MATERIALIZED VIEW ... IS '...';
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = HERE / "schema.sql"
TEMPLATE = HERE / "erd_template.html"
OUTPUT = HERE / "index.html"

TYPE_RE = re.compile(r"^(\w+(?:\s+precision)?(?:\s*\([^)]*\))?(?:\[\])?)", re.I)
REF_RE = re.compile(r"REFERENCES\s+([\w.\"]+)\s*\(([^)]*)\)", re.I)
COMMENT_RE = re.compile(
    r"COMMENT ON (SCHEMA|TABLE|COLUMN|MATERIALIZED VIEW|FUNCTION)\s+(.+?)\s+IS\s+'((?:[^']|'')*)';",
    re.S,
)
INDEX_RE = re.compile(
    r"^CREATE (UNIQUE )?INDEX (\w+) ON ([\w.\"]+)(?: USING (\w+))? \((.*)\)(?: WHERE (.*))?;$"
)
ALTER_FK_RE = re.compile(
    r"^ALTER TABLE ([\w.\"]+) ADD CONSTRAINT \w+ FOREIGN KEY \(([^)]*)\) REFERENCES ([\w.\"]+) \(([^)]*)\)"
)
CONSTRAINT_RE = re.compile(r"^(PRIMARY KEY|FOREIGN KEY|UNIQUE|CHECK|CONSTRAINT|EXCLUDE)\b(?!_)", re.I)


def clean(name: str) -> str:
    return name.replace('"', "").strip()


def split_cols(s: str):
    return [clean(c) for c in s.split(",") if c.strip()]


def parse(sql: str):
    domains, tables, views, schemas = [], {}, {}, {}
    current = None
    lines = sql.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^-- @domain (\w+) \| ([^|]+)\|\s*(.*)$", line)
        if m:
            current = {"key": m.group(1), "title": m.group(2).strip(), "desc": m.group(3).strip(), "tables": []}
            domains.append(current)
            i += 1
            continue

        m = re.match(r"^CREATE TABLE ([\w.\"]+) PARTITION OF ([\w.\"]+) (.*);$", line)
        if m:
            parent = tables[clean(m.group(2))]
            parent["partitions"].append({"name": clean(m.group(1)), "bound": m.group(3)})
            i += 1
            continue

        m = re.match(r"^CREATE TABLE ([\w.\"]+) \($", line)
        if m:
            name = clean(m.group(1))
            t = {
                "name": name, "schema": name.split(".")[0], "domain": current["key"] if current else None,
                "comment": "", "columns": [], "pk": [], "uniques": [], "checks": 0, "fks": [],
                "indexes": [], "partitions": [], "partition_by": None,
            }
            i += 1
            while not lines[i].startswith(")"):
                raw = lines[i].strip().rstrip(",")
                i += 1
                if not raw:
                    continue
                upper = raw.upper()
                if CONSTRAINT_RE.match(raw):
                    if upper.startswith("PRIMARY KEY"):
                        t["pk"] = split_cols(re.search(r"\((.*)\)", raw).group(1))
                    elif upper.startswith("FOREIGN KEY"):
                        fm = re.match(r"FOREIGN KEY \(([^)]*)\) REFERENCES ([\w.\"]+) \(([^)]*)\)", raw, re.I)
                        t["fks"].append({"cols": split_cols(fm.group(1)), "ref": clean(fm.group(2)), "ref_cols": split_cols(fm.group(3))})
                    elif upper.startswith("UNIQUE"):
                        t["uniques"].append(split_cols(re.search(r"\(([^()]*)\)\s*$", raw).group(1)))
                    else:
                        t["checks"] += 1
                    continue
                cm = re.match(r"^(\"?\w+\"?)\s+(.*)$", raw)
                col_name, rest = clean(cm.group(1)), cm.group(2)
                tm = TYPE_RE.match(rest)
                ctype = re.sub(r"\s+", " ", tm.group(1)) if tm else rest.split()[0]
                ru = rest.upper()
                col = {
                    "name": col_name, "type": ctype,
                    "pk": "PRIMARY KEY" in ru,
                    "nn": "NOT NULL" in ru or "PRIMARY KEY" in ru,
                    "uq": bool(re.search(r"\bUNIQUE\b", ru)),
                    "identity": "GENERATED" in ru,
                    "default": None, "fk": None, "comment": "",
                }
                dm = re.search(r"DEFAULT (.+?)(?: CHECK| REFERENCES| NOT NULL|$)", rest)
                if dm:
                    col["default"] = dm.group(1).strip()
                if "CHECK" in ru:
                    t["checks"] += 1
                rm = REF_RE.search(rest)
                if rm:
                    col["fk"] = {"table": clean(rm.group(1)), "col": split_cols(rm.group(2))[0]}
                    t["fks"].append({"cols": [col_name], "ref": clean(rm.group(1)), "ref_cols": split_cols(rm.group(2))})
                if col["pk"]:
                    t["pk"] = [col_name]
                t["columns"].append(col)
            pm = re.search(r"PARTITION BY (\w+) \((\w+)\)", lines[i])
            if pm:
                t["partition_by"] = f"{pm.group(1)} ({pm.group(2)})"
            tables[name] = t
            if current:
                current["tables"].append(name)
            i += 1
            continue

        m = re.match(r"^CREATE MATERIALIZED VIEW ([\w.\"]+) AS", line)
        if m:
            name = clean(m.group(1))
            body = []
            i += 1
            while not lines[i].rstrip().endswith(";"):
                body.append(lines[i])
                i += 1
            body.append(lines[i])
            views[name] = {"name": name, "domain": current["key"] if current else None, "comment": "", "sql": "\n".join(body).strip(), "indexes": []}
            i += 1
            continue

        m = ALTER_FK_RE.match(line)
        if m:
            t = tables[clean(m.group(1))]
            cols = split_cols(m.group(2))
            ref = clean(m.group(3))
            t["fks"].append({"cols": cols, "ref": ref, "ref_cols": split_cols(m.group(4))})
            for c in t["columns"]:
                if c["name"] == cols[0] and len(cols) == 1:
                    c["fk"] = {"table": ref, "col": split_cols(m.group(4))[0]}
            i += 1
            continue

        m = INDEX_RE.match(line)
        if m:
            target = clean(m.group(3))
            idx = {"name": m.group(2), "unique": bool(m.group(1)), "method": m.group(4) or "btree", "expr": m.group(5), "where": m.group(6)}
            (tables.get(target) or views.get(target) or {"indexes": []})["indexes"].append(idx)
        i += 1

    # Table-level composite FKs mark member columns as FK too
    for t in tables.values():
        for fk in t["fks"]:
            for c in t["columns"]:
                if c["name"] in fk["cols"] and not c["fk"]:
                    c["fk"] = {"table": fk["ref"], "col": fk["ref_cols"][fk["cols"].index(c["name"])]}
        for c in t["columns"]:
            if c["name"] in t["pk"]:
                c["pk"] = True
                c["nn"] = True
            if any(u == [c["name"]] for u in t["uniques"]):
                c["uq"] = True

    for kind, target, text in COMMENT_RE.findall(sql):
        text = text.replace("''", "'")
        target = clean(target)
        if kind == "SCHEMA":
            schemas[target] = text
        elif kind == "TABLE" and target in tables:
            tables[target]["comment"] = text
        elif kind == "MATERIALIZED VIEW" and target in views:
            views[target]["comment"] = text
        elif kind == "COLUMN":
            tname, cname = target.rsplit(".", 1)
            for c in tables.get(tname, {"columns": []})["columns"]:
                if c["name"] == cname:
                    c["comment"] = text
    return domains, tables, views, schemas


def main():
    sql = SCHEMA.read_text(encoding="utf-8")
    domains, tables, views, schemas = parse(sql)

    problems = []
    for t in tables.values():
        if not t["comment"]:
            problems.append(f"bảng {t['name']} thiếu COMMENT")
        for c in t["columns"]:
            if not c["comment"]:
                problems.append(f"cột {t['name']}.{c['name']} thiếu COMMENT")
        for fk in t["fks"]:
            if fk["ref"] not in tables:
                problems.append(f"{t['name']} tham chiếu bảng không tồn tại {fk['ref']}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        sys.exit(1)

    data = {
        "domains": domains,
        "tables": tables,
        "views": views,
        "schemas": schemas,
        "stats": {
            "tables": len(tables),
            "columns": sum(len(t["columns"]) for t in tables.values()),
            "fks": sum(len(t["fks"]) for t in tables.values()),
            "indexes": sum(len(t["indexes"]) for t in tables.values()) + sum(len(v["indexes"]) for v in views.values()),
            "views": len(views),
            "partitions": sum(len(t["partitions"]) for t in tables.values()),
        },
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__ERD_DATA__*/null", payload)
    OUTPUT.write_text(html, encoding="utf-8")
    s = data["stats"]
    print(f"OK: {s['tables']} bảng, {s['columns']} cột, {s['fks']} khoá ngoại, {s['indexes']} index, "
          f"{s['views']} materialized view, {s['partitions']} partition → {OUTPUT.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
