#!/usr/bin/env python3
"""Stage 5 — Assemble metric_view.yaml + create_view.sql (Mode A) or
numbered .sql files (Mode B: regular SQL gold schema).

Mode A (default): One Metric View YAML spec per fact group + CREATE VIEW DDL.
  Models with multiple fact tables produce multiple metric_view_<fact>.yaml files,
  each with its own source, joins, dimensions, and measures.
  Also generates conversion_details.xlsx with full source→target mapping.
Mode B (--mode-b): Delta tables, views, materialized views, gold schema objects.

Usage:
  python build_view.py --workdir conversion/sales
  python build_view.py --workdir conversion/sales --mode-b
"""
import argparse, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from _shared import snake, load_json, save_json, save_text

try:
    import yaml

    class _LiteralStr(str):
        pass

    def _literal_representer(dumper, data):
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")

    yaml.add_representer(_LiteralStr, _literal_representer)
except ImportError:
    yaml = None
    _LiteralStr = str


def build_joins_dims(fact, model, phys, aliases, profile_data):
    """Build joins and dimensions for a single fact table."""
    tables = {t["name"]: t for t in model["tables"]}

    date_fix, numeric_warn = {}, []
    if profile_data:
        for tname, entry in profile_data.get("tables", {}).items():
            for flag in entry.get("column_reconciliation", {}).get("dtype_flags", []):
                if flag["issue"] == "string_date":
                    date_fix[(tname, flag["column"])] = True
                elif flag["issue"] == "varchar_numeric":
                    numeric_warn.append(f"{tname}.{flag['column']}")

    joins = []
    for r in model["relationships"]:
        if not r["is_active"]:
            continue
        if r["from_table"] == fact and r["to_table"] in phys:
            alias = aliases.get(r["to_table"], snake(r["to_table"]))
            joins.append({"name": alias, "source": phys[r["to_table"]],
                          "on": f"source.{snake(r['from_column'])} = {alias}.{snake(r['to_column'])}"})

    dims = []
    joined = {j["name"] for j in joins}
    for tname, t in tables.items():
        alias = "source" if tname == fact else aliases.get(tname, snake(tname))
        if tname != fact and alias not in joined:
            continue
        for c in t["columns"]:
            if c.get("isHidden"):
                continue
            col_expr = f"{alias}.{snake(c['name'])}"
            if date_fix.get((tname, c["name"])):
                col_expr = f"to_date({col_expr})"
            dims.append({"name": c["name"], "expr": col_expr})
        for h in t.get("hierarchies", []):
            for i, lvl in enumerate(h["levels"]):
                dims.append({"name": f"{h['name']} L{i+1} ({lvl})",
                             "expr": f"{alias}.{snake(lvl)}"})
    seen, dedup = set(), []
    for d in dims:
        if d["name"] not in seen:
            seen.add(d["name"])
            dedup.append(d)

    return joins, dedup, date_fix, numeric_warn


def _strip_lines(text):
    """Strip trailing whitespace from each line."""
    return "\n".join(line.rstrip() for line in text.splitlines())


_SELECTEDVALUE_RE = re.compile(r"\bSELECTEDVALUE\s*\(", re.I)
_STATIC_STR_RE = re.compile(r"""^\s*(['"])[^'"]*\1\s*$""")


def _invalid_measure_reason(sql, original_dax=""):
    """Return a reason string if the SQL is not a valid metric view expression,
    or None if it's valid. Catches PBI visual-layer patterns that passed
    translation as syntactically simple but are semantically wrong."""
    s = sql.strip()
    dax = (original_dax or "").strip()
    if _SELECTEDVALUE_RE.search(s) or _SELECTEDVALUE_RE.search(dax):
        return "SELECTEDVALUE is a DAX visual-layer function with no metric view equivalent"
    if _STATIC_STR_RE.match(s):
        return "Static string literal — not a metric/aggregation"
    if '"' in s and "&" in s and not re.search(r"\b(sum|count|avg|min|max|try_divide|MEASURE)\s*\(", s, re.I):
        return "String concatenation expression — PBI report title, not a measure"
    return None


def write_conversion_excel(wd, converted_rows, review_rows):
    """Write conversion_details.xlsx with two sheets."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        print("  WARNING: openpyxl not installed — skipping Excel. Install: pip install openpyxl")
        return

    wb = Workbook()
    thin = Side(style="thin", color="CCCCCC")
    border = Border(bottom=thin)
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font_w = Font(bold=True, size=11, color="FFFFFF")
    wrap = Alignment(wrap_text=True, vertical="top")
    top_align = Alignment(vertical="top")

    def style_sheet(ws, headers, rows):
        ws.append(headers)
        for ci, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=ci)
            cell.font = header_font_w
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for row in rows:
            ws.append(row)
        for ri in range(2, ws.max_row + 1):
            for ci in range(1, ws.max_column + 1):
                cell = ws.cell(row=ri, column=ci)
                cell.alignment = wrap if ci in (3, 4, 10) else top_align
                cell.border = border
        for ci in range(1, ws.max_column + 1):
            max_len = max((len(str(ws.cell(row=r, column=ci).value or "")[:60])
                           for r in range(1, min(ws.max_row + 1, 50))), default=10)
            ws.column_dimensions[ws.cell(row=1, column=ci).column_letter].width = min(max(max_len + 2, 12), 50)
        ws.auto_filter.ref = ws.dimensions
        ws.freeze_panes = "A2"

    conv_headers = [
        "Measure Name", "Metric View File", "Fact Table", "Target Source",
        "Status", "Tier", "Score", "Description", "Folder",
        "Converted SQL Expression"
    ]
    ws1 = wb.active
    ws1.title = "Converted Measures"
    style_sheet(ws1, conv_headers, converted_rows)

    review_headers = [
        "Measure Name", "Fact Table", "Target Source",
        "Status", "Tier", "Score", "Category", "Description", "Folder",
        "Original DAX", "Stub / Candidate SQL", "Notes"
    ]
    ws2 = wb.create_sheet("Manual Review Required")
    style_sheet(ws2, review_headers, review_rows)

    path = os.path.join(wd, "conversion_details.xlsx")
    wb.save(path)
    print(f"conversion_details.xlsx: {len(converted_rows)} converted, {len(review_rows)} manual review")


def build_mode_a(wd, model, tr, tm, profile_data):
    """Build Metric View YAML spec + CREATE VIEW DDL — one per fact group.
    Only auto-converted measures go into the YAML.
    All measures go into the Excel report."""
    phys = tm["physical"]
    fact_groups = tm.get("fact_groups", [])

    if not fact_groups:
        fact_groups = [{
            "name": tm["fact"],
            "view_name": tm["view_name"],
            "aliases": tm.get("aliases", {}),
            "joins_from": [],
            "dim_tables": []
        }]

    descriptions = {m["name"]: m.get("description") for t in model["tables"] for m in t["measures"]}
    folders = {m["name"]: m.get("displayFolder") for t in model["tables"] for m in t["measures"]}

    yaml_include = {"auto", "auto_spot_check", "reviewed"}

    measures_by_group = {}
    ungrouped = []
    for name, m in tr["measures"].items():
        fg = m.get("fact_group")
        if fg:
            measures_by_group.setdefault(fg, []).append((name, m))
        else:
            ungrouped.append((name, m))

    if ungrouped and fact_groups:
        primary = fact_groups[0]["name"]
        measures_by_group.setdefault(primary, []).extend(ungrouped)

    multi = len(fact_groups) > 1
    total_views = 0
    excel_converted = []
    excel_review = []

    for fg in fact_groups:
        fact = fg["name"]
        if fact not in phys:
            continue
        aliases = fg.get("aliases", {fact: "source"})
        if fact not in aliases:
            aliases[fact] = "source"

        joins, dedup, date_fix, numeric_warn = build_joins_dims(
            fact, model, phys, aliases, profile_data)

        for rp in tm.get("role_playing", []):
            joins.append({"name": rp["alias"], "source": rp["physical"], "on": rp["on"]})

        suffix = f"_{snake(fact)}" if multi else ""
        yaml_name = f"metric_view{suffix}.yaml"

        measures, excluded = [], []
        for name, m in measures_by_group.get(fact, []):
            sql_clean = m["sql"].strip()
            is_stub = sql_clean.startswith("-- TODO") or sql_clean.startswith("-- UNSUPPORTED")
            is_convertible = m["status"] in yaml_include and not is_stub
            invalid_reason = _invalid_measure_reason(sql_clean, m.get("original_dax", "")) if is_convertible else None

            if is_convertible and not invalid_reason:
                desc = descriptions.get(name) or ""
                sql_text = _strip_lines(sql_clean)
                entry = {"name": name}
                if desc:
                    entry["description"] = desc
                if "\n" in sql_text:
                    entry["expr"] = _LiteralStr(sql_text)
                else:
                    entry["expr"] = sql_text
                measures.append(entry)

                excel_converted.append([
                    name, yaml_name, fact, phys[fact],
                    m["status"], m.get("tier", ""), m.get("score", ""),
                    desc, folders.get(name, ""),
                    sql_clean
                ])
            else:
                reason = invalid_reason or m["status"]
                excluded.append((name, reason))
                notes_list = list(m.get("notes", []))
                if invalid_reason:
                    notes_list.insert(0, invalid_reason)
                excel_review.append([
                    name, fact, phys.get(fact, ""),
                    m["status"] if not invalid_reason else f"{m['status']} (invalid)",
                    m.get("tier", ""), m.get("score", ""),
                    m.get("category", ""), descriptions.get(name, ""),
                    folders.get(name, ""),
                    m.get("original_dax", ""), sql_clean, "; ".join(notes_list)
                ])

        if not measures:
            continue

        spec = {"version": "1.1", "source": phys[fact], "joins": joins,
                "dimensions": dedup, "measures": measures}
        if yaml:
            spec_yaml = yaml.dump(spec, sort_keys=False, width=100, allow_unicode=True)
        else:
            import json
            spec_yaml = json.dumps(spec, indent=2)

        view_name = fg.get("view_name", tm["view_name"])
        sql_name = f"create_view{suffix}.sql"

        save_text(spec_yaml, os.path.join(wd, yaml_name))
        ddl = (f"-- DRY RUN — review before executing against a governed catalog.\n"
               f"-- Verify current Metric View syntax against Databricks docs (evolving feature).\n"
               f"CREATE OR REPLACE VIEW {view_name}\nWITH METRICS\nLANGUAGE YAML\n"
               f"AS $$\n{spec_yaml}$$;")
        save_text(ddl, os.path.join(wd, sql_name))
        total_views += 1
        print(f"{yaml_name}: source={fact}, {len(joins)} joins, {len(dedup)} dims, {len(measures)} measures")
        if excluded:
            print(f"  excluded ({len(excluded)}): " +
                  ", ".join(f"{n} [{s}]" for n, s in excluded[:10]) +
                  (" ..." if len(excluded) > 10 else ""))
        if date_fix:
            print(f"  auto-cast to_date() applied to {len(date_fix)} dimension column(s)")
        if numeric_warn:
            print(f"  WARNING: varchar_numeric flag on {numeric_warn} — confirm try_cast in measure SQL")

    if total_views > 1:
        print(f"  TOTAL: {total_views} metric views generated from {len(fact_groups)} fact groups")

    write_conversion_excel(wd, excel_converted, excel_review)


def build_mode_b(wd, model, tr, tm, profile_data):
    """Build regular SQL gold schema: fact_, dim_, vw_, mv_, gold_, pbi_ prefixed objects."""
    fact, phys, aliases = tm["fact"], tm["physical"], tm.get("aliases", {})
    catalog_schema = tm.get("view_name", "catalog.schema.model").rsplit(".", 1)[0]
    tables = {t["name"]: t for t in model["tables"]}
    sqls = []
    seq = 0

    seq += 1
    dim_sqls = []
    for r in model["relationships"]:
        if not r["is_active"]:
            continue
        dim_name = r["to_table"]
        if dim_name not in phys:
            continue
        dim_alias = snake(dim_name)
        dim_sqls.append(
            f"CREATE OR REPLACE VIEW {catalog_schema}.dim_{dim_alias} AS\n"
            f"SELECT * FROM {phys[dim_name]};")
    if dim_sqls:
        sqls.append((f"{seq:02d}_dimension_views.sql", "\n\n".join(dim_sqls)))

    seq += 1
    fact_alias = snake(fact)
    sqls.append((f"{seq:02d}_fact_view.sql",
                 f"CREATE OR REPLACE VIEW {catalog_schema}.fact_{fact_alias} AS\n"
                 f"SELECT * FROM {phys[fact]};"))

    seq += 1
    join_clauses = []
    for r in model["relationships"]:
        if not r["is_active"] or r["to_table"] not in phys:
            continue
        dim_alias = snake(r["to_table"])
        join_clauses.append(
            f"LEFT JOIN {catalog_schema}.dim_{dim_alias} {dim_alias}\n"
            f"  ON f.{snake(r['from_column'])} = {dim_alias}.{snake(r['to_column'])}")
    star_sql = (f"CREATE OR REPLACE VIEW {catalog_schema}.vw_{fact_alias}_star AS\n"
                f"SELECT f.*, " +
                ", ".join(f"{snake(r['to_table'])}.*" for r in model["relationships"]
                          if r["is_active"] and r["to_table"] in phys) +
                f"\nFROM {catalog_schema}.fact_{fact_alias} f\n" +
                "\n".join(join_clauses) + ";")
    sqls.append((f"{seq:02d}_star_join_view.sql", star_sql))

    seq += 1
    measure_sqls = []
    for name, m in tr["measures"].items():
        if m["status"] in ("auto", "auto_spot_check", "reviewed"):
            safe_name = snake(name)
            measure_sqls.append(
                f"-- DAX: {m['original_dax'].strip()}\n"
                f"-- Score: {m.get('score', '?')} | Band: {m.get('tier', '?')}\n"
                f"CREATE OR REPLACE VIEW {catalog_schema}.pbi_{safe_name} AS\n"
                f"SELECT {m['sql']} AS {safe_name}\n"
                f"FROM {catalog_schema}.vw_{fact_alias}_star;")
    if measure_sqls:
        sqls.append((f"{seq:02d}_measure_views.sql", "\n\n".join(measure_sqls)))

    seq += 1
    gold_cols = []
    for name, m in tr["measures"].items():
        if m["status"] in ("auto", "auto_spot_check", "reviewed"):
            gold_cols.append(f"  {m['sql']} AS {snake(name)}")
    if gold_cols:
        sqls.append((f"{seq:02d}_gold_wide_view.sql",
                     f"CREATE OR REPLACE VIEW {catalog_schema}.gold_{fact_alias} AS\n"
                     f"SELECT\n" + ",\n".join(gold_cols) +
                     f"\nFROM {catalog_schema}.vw_{fact_alias}_star;"))

    for fname, content in sqls:
        save_text(content, os.path.join(wd, fname))
    print(f"Mode B: wrote {len(sqls)} SQL files with fact_/dim_/vw_/pbi_/gold_ prefixes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--mode-b", action="store_true", help="Regular SQL gold schema instead of Metric View YAML")
    a = ap.parse_args()
    wd = a.workdir
    model = load_json(os.path.join(wd, "model.json"), "model.json")
    tr = load_json(os.path.join(wd, "translations.json"), "translations.json")
    tm = load_json(os.path.join(wd, "table_map.json"), "table_map.json")

    profile_data = None
    profile_path = os.path.join(wd, "profile.json")
    if os.path.exists(profile_path):
        profile_data = load_json(profile_path, "profile.json")

    if a.mode_b:
        build_mode_b(wd, model, tr, tm, profile_data)
    else:
        build_mode_a(wd, model, tr, tm, profile_data)


if __name__ == "__main__":
    main()
