#!/usr/bin/env python3
"""Stage 5b — Generate wrapper views on top of metric views.

Wrapper views use window functions, LAG/LEAD, CTEs, and RANK that cannot
live inside a metric view expr. They cover time intelligence (YoY, YTD, MoM),
ratio-of-total (ALL-family), ranking (RANKX), rolling averages, and
conditional measures (CALCULATE with boolean filters).

Reads translations.json + classification.json + table_map.json + model.json.
Writes wrapper_view_<fact>.sql per fact group.

Usage:
  python build_wrapper.py --workdir conversion/sales
"""
import argparse, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from _shared import snake, load_json, save_text

# ── Pattern detection regexes ────────────────────────────────────────────────

SPLY_RE = re.compile(r"\bSAMEPERIODLASTYEAR\s*\(", re.I)
DATEADD_RE = re.compile(r"\bDATEADD\s*\(", re.I)
PARALLEL_RE = re.compile(r"\bPARALLELPERIOD\s*\(", re.I)
YTD_RE = re.compile(r"\b(TOTALYTD|DATESYTD)\s*\(", re.I)
QTD_RE = re.compile(r"\b(TOTALQTD|DATESQTD)\s*\(", re.I)
MTD_RE = re.compile(r"\b(TOTALMTD|DATESMTD)\s*\(", re.I)
ALL_RE = re.compile(r"\b(ALL|ALLEXCEPT|REMOVEFILTERS|ALLSELECTED)\s*\(", re.I)
RANKX_RE = re.compile(r"\bRANKX\s*\(", re.I)
ROLLING_RE = re.compile(r"\bDATESINPERIOD\s*\(", re.I)
LASTNONBLANK_RE = re.compile(r"\b(LASTNONBLANK|LASTDATE|CLOSINGBALANCE\w*)\s*\(", re.I)
CALCULATE_RE = re.compile(r"\bCALCULATE\s*\(", re.I)

MEASURE_REF_RE = re.compile(r"\[([^\]]+)\]")


def classify_wrapper_pattern(dax):
    """Classify which wrapper pattern a DAX expression needs.
    Returns (pattern_name, sub_type) or (None, None) if not wrappable."""
    if SPLY_RE.search(dax):
        return "prior_period", "year"
    if DATEADD_RE.search(dax):
        m = re.search(r"DATEADD\s*\([^,]*,\s*(-?\d+)\s*,\s*(\w+)", dax, re.I)
        if m:
            offset, unit = int(m.group(1)), m.group(2).upper()
            return "prior_period", f"{abs(offset)}_{unit.lower()}"
        return "prior_period", "custom"
    if PARALLEL_RE.search(dax):
        return "prior_period", "parallel"
    if YTD_RE.search(dax):
        return "to_date", "ytd"
    if QTD_RE.search(dax):
        return "to_date", "qtd"
    if MTD_RE.search(dax):
        return "to_date", "mtd"
    if RANKX_RE.search(dax):
        return "rank", "dense"
    if ROLLING_RE.search(dax):
        return "rolling", "period"
    if LASTNONBLANK_RE.search(dax):
        return "semi_additive", "last"
    if ALL_RE.search(dax) and CALCULATE_RE.search(dax):
        return "ratio_of_total", "all"
    return None, None


def find_date_dim(model, fact_name, tm):
    """Find the date dimension table joined to a fact, with column mappings."""
    aliases = tm.get("aliases", {})
    for r in model["relationships"]:
        if not r.get("is_active", True):
            continue
        if r["from_table"] != fact_name:
            continue
        dim = r["to_table"]
        dim_lower = dim.lower().replace("-", "").replace("_", "").replace(" ", "")
        if any(kw in dim_lower for kw in ("date", "calendar", "time", "period")):
            dim_alias = aliases.get(dim, snake(dim))
            tables = {t["name"]: t for t in model["tables"]}
            dim_cols = [c["name"] for c in tables.get(dim, {}).get("columns", [])
                        if not c.get("isHidden")]
            year_col = next((c for c in dim_cols
                             if re.match(r"(calendar|fiscal)?_?year$", snake(c), re.I)), None)
            month_col = next((c for c in dim_cols
                              if re.match(r"(calendar|fiscal)?_?month(_?number)?$", snake(c), re.I)), None)
            quarter_col = next((c for c in dim_cols
                                if re.match(r"(calendar|fiscal)?_?quarter$", snake(c), re.I)), None)
            date_col = next((c for c in dim_cols
                             if re.match(r"(full_?date|date_?key|date)$", snake(c), re.I)), None)
            return {
                "table": dim, "alias": dim_alias,
                "year": snake(year_col) if year_col else None,
                "month": snake(month_col) if month_col else None,
                "quarter": snake(quarter_col) if quarter_col else None,
                "date": snake(date_col) if date_col else None,
                "fk_column": snake(r["from_column"]),
            }
    return None


def find_base_measure(dax, translated_measures):
    """Find which metric view measure a DAX expression depends on."""
    refs = MEASURE_REF_RE.findall(dax)
    for ref in refs:
        if ref in translated_measures:
            m = translated_measures[ref]
            if m["status"] in ("auto", "auto_spot_check", "reviewed"):
                return ref
    return None


def gen_prior_period_sql(name, base_measure, date_info, sub_type, view_name):
    """Generate LAG-based prior period wrapper."""
    if not date_info or not date_info["date"]:
        return None
    d = date_info["alias"]
    date_col = f"{d}.{date_info['date']}"

    if sub_type == "year":
        return (
            f"  LAG(MEASURE(`{base_measure}`), 12) OVER (\n"
            f"    ORDER BY {date_col}\n"
            f"  ) AS `{name}`"
        )
    elif "month" in sub_type:
        offset = int(sub_type.split("_")[0]) if sub_type[0].isdigit() else 1
        return (
            f"  LAG(MEASURE(`{base_measure}`), {offset}) OVER (\n"
            f"    ORDER BY {date_col}\n"
            f"  ) AS `{name}`"
        )
    return (
        f"  LAG(MEASURE(`{base_measure}`)) OVER (\n"
        f"    ORDER BY {date_col}\n"
        f"  ) AS `{name}`"
    )


def gen_to_date_sql(name, base_measure, date_info, sub_type, view_name):
    """Generate running-SUM YTD/QTD/MTD wrapper."""
    if not date_info or not date_info["date"]:
        return None
    d = date_info["alias"]
    date_col = f"{d}.{date_info['date']}"

    if sub_type == "ytd" and date_info["year"]:
        part_col = f"{d}.{date_info['year']}"
    elif sub_type == "qtd" and date_info["quarter"] and date_info["year"]:
        part_col = f"{d}.{date_info['year']}, {d}.{date_info['quarter']}"
    elif sub_type == "mtd" and date_info["month"] and date_info["year"]:
        part_col = f"{d}.{date_info['year']}, {d}.{date_info['month']}"
    else:
        return None

    return (
        f"  SUM(MEASURE(`{base_measure}`)) OVER (\n"
        f"    PARTITION BY {part_col}\n"
        f"    ORDER BY {date_col}\n"
        f"    ROWS UNBOUNDED PRECEDING\n"
        f"  ) AS `{name}`"
    )


def gen_ratio_sql(name, base_measure, date_info, sub_type, view_name):
    """Generate pct-of-total wrapper with SUM OVER ()."""
    return (
        f"  try_divide(\n"
        f"    MEASURE(`{base_measure}`),\n"
        f"    SUM(MEASURE(`{base_measure}`)) OVER ()\n"
        f"  ) AS `{name}`"
    )


def gen_rank_sql(name, base_measure, date_info, sub_type, view_name):
    """Generate RANK/DENSE_RANK wrapper."""
    return (
        f"  DENSE_RANK() OVER (\n"
        f"    ORDER BY MEASURE(`{base_measure}`) DESC\n"
        f"  ) AS `{name}`"
    )


def gen_yoy_change_sql(name, base_measure, prior_name, dax):
    """Generate YoY/MoM change and change % from a prior period + base."""
    is_pct = re.search(r"DIVIDE|%", dax, re.I)
    if is_pct:
        return (
            f"  try_divide(\n"
            f"    `{base_measure}` - `{prior_name}`,\n"
            f"    `{prior_name}`\n"
            f"  ) AS `{name}`"
        )
    return f"  `{base_measure}` - `{prior_name}` AS `{name}`"


GENERATORS = {
    "prior_period": gen_prior_period_sql,
    "to_date": gen_to_date_sql,
    "ratio_of_total": gen_ratio_sql,
    "rank": gen_rank_sql,
}


def build_wrappers(wd, model, tr, cls, tm):
    """Build wrapper view SQL files for measures excluded from metric views."""
    phys = tm["physical"]
    fact_groups = tm.get("fact_groups", [])
    if not fact_groups:
        fact_groups = [{"name": tm["fact"], "view_name": tm["view_name"],
                        "aliases": tm.get("aliases", {})}]

    measures_by_group = {}
    for name, m in tr["measures"].items():
        fg = m.get("fact_group")
        if fg:
            measures_by_group.setdefault(fg, []).append((name, m))
        else:
            if fact_groups:
                measures_by_group.setdefault(fact_groups[0]["name"], []).append((name, m))

    multi = len(fact_groups) > 1
    total_wrapped = 0
    total_skipped = 0
    excel_rows = []

    for fg in fact_groups:
        fact = fg["name"]
        if fact not in phys:
            continue
        view_name = fg.get("view_name", tm["view_name"])
        date_info = find_date_dim(model, fact, tm)

        wrapper_columns = []
        group_by_dims = set()
        wrapped_measures = []
        prior_period_map = {}

        for name, m in measures_by_group.get(fact, []):
            if m["status"] in ("auto", "auto_spot_check", "reviewed"):
                continue
            dax = m.get("original_dax", "")
            pattern, sub_type = classify_wrapper_pattern(dax)
            if not pattern:
                total_skipped += 1
                continue

            base = find_base_measure(dax, tr["measures"])
            if not base and pattern in ("prior_period", "to_date"):
                inner_refs = MEASURE_REF_RE.findall(dax)
                for ref in inner_refs:
                    if ref in tr["measures"] and tr["measures"][ref]["status"] in ("auto", "auto_spot_check", "reviewed"):
                        base = ref
                        break

            if not base:
                c = cls["measures"].get(name, {})
                excel_rows.append([
                    name, fact, pattern, sub_type, dax,
                    "SKIPPED: no base measure found in metric view",
                    m["status"], c.get("score", ""), c.get("tier", "")
                ])
                total_skipped += 1
                continue

            gen_fn = GENERATORS.get(pattern)
            if not gen_fn:
                total_skipped += 1
                continue

            col_sql = gen_fn(name, base, date_info, sub_type, view_name)
            if not col_sql:
                c = cls["measures"].get(name, {})
                excel_rows.append([
                    name, fact, pattern, sub_type, dax,
                    f"SKIPPED: missing date dimension info for {pattern}",
                    m["status"], c.get("score", ""), c.get("tier", "")
                ])
                total_skipped += 1
                continue

            wrapper_columns.append(col_sql)
            wrapped_measures.append(name)
            if pattern == "prior_period":
                prior_period_map[name] = base

            if date_info:
                if date_info["date"]:
                    group_by_dims.add(f"{date_info['alias']}.{date_info['date']}")
                if date_info["year"]:
                    group_by_dims.add(f"{date_info['alias']}.{date_info['year']}")
                if date_info["month"]:
                    group_by_dims.add(f"{date_info['alias']}.{date_info['month']}")
                if date_info["quarter"]:
                    group_by_dims.add(f"{date_info['alias']}.{date_info['quarter']}")

            c = cls["measures"].get(name, {})
            excel_rows.append([
                name, fact, pattern, sub_type, dax, col_sql.strip(),
                "WRAPPED", c.get("score", ""), c.get("tier", "")
            ])

        # Check for YoY/MoM change measures that reference a prior period measure
        for name, m in measures_by_group.get(fact, []):
            if m["status"] in ("auto", "auto_spot_check", "reviewed"):
                continue
            dax = m.get("original_dax", "")
            refs = MEASURE_REF_RE.findall(dax)
            prior_ref = None
            base_ref = None
            for ref in refs:
                if ref in prior_period_map:
                    prior_ref = ref
                    base_ref = prior_period_map[ref]
                elif ref in tr["measures"] and tr["measures"][ref]["status"] in ("auto", "auto_spot_check", "reviewed"):
                    base_ref = base_ref or ref

            if prior_ref and base_ref and name not in wrapped_measures:
                if re.search(r"DIVIDE|change|growth|%|yoy|mom", dax + name, re.I):
                    change_sql = gen_yoy_change_sql(name, base_ref, prior_ref, dax)
                    wrapper_columns.append(change_sql)
                    wrapped_measures.append(name)
                    c = cls["measures"].get(name, {})
                    excel_rows.append([
                        name, fact, "yoy_change", "derived", dax, change_sql.strip(),
                        "WRAPPED", c.get("score", ""), c.get("tier", "")
                    ])

        if not wrapper_columns:
            continue

        base_measures_used = set()
        for name_w in wrapped_measures:
            for mname, m in measures_by_group.get(fact, []):
                if mname == name_w:
                    dax = m.get("original_dax", "")
                    base = find_base_measure(dax, tr["measures"])
                    if base:
                        base_measures_used.add(base)
                    break
        for pp_name, pp_base in prior_period_map.items():
            base_measures_used.add(pp_base)

        base_cols = [f"  MEASURE(`{b}`) AS `{b}`" for b in sorted(base_measures_used)]
        dims_str = ",\n  ".join(sorted(group_by_dims)) if group_by_dims else "-- add dimensions"
        suffix = f"_{snake(fact)}" if multi else ""
        wrapper_name = f"{view_name}_wrapper"

        all_cols = base_cols + wrapper_columns
        cols_block = ",\n".join(all_cols)
        sql = (
            f"-- Wrapper view for measures that need window functions / LAG / RANK.\n"
            f"-- Sits on top of the metric view and adds time intelligence,\n"
            f"-- ratio-of-total, ranking, and derived change measures.\n"
            f"-- REVIEW: verify date dimension columns and GROUP BY grain.\n\n"
            f"CREATE OR REPLACE VIEW {wrapper_name} AS\n"
            f"SELECT\n"
            f"  {dims_str},\n"
            f"{cols_block}\n"
            f"FROM {view_name}\n"
            f"GROUP BY {dims_str};\n"
        )

        fname = f"wrapper_view{suffix}.sql"
        save_text(sql, os.path.join(wd, fname))
        total_wrapped += len(wrapped_measures)
        print(f"{fname}: {len(wrapped_measures)} measures wrapped ({', '.join(wrapped_measures[:5])}{'...' if len(wrapped_measures) > 5 else ''})")

    write_wrapper_excel(wd, excel_rows)
    print(f"  TOTAL: {total_wrapped} wrapped, {total_skipped} skipped (no pattern or missing base)")
    return total_wrapped


def write_wrapper_excel(wd, rows):
    """Add a 'Wrapper Views' sheet to the existing conversion_details.xlsx."""
    if not rows:
        return
    try:
        from openpyxl import load_workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        print("  WARNING: openpyxl not installed — skipping wrapper Excel update")
        return

    xlsx_path = os.path.join(wd, "conversion_details.xlsx")
    if os.path.exists(xlsx_path):
        wb = load_workbook(xlsx_path)
    else:
        from openpyxl import Workbook
        wb = Workbook()

    if "Wrapper Views" in wb.sheetnames:
        del wb["Wrapper Views"]
    ws = wb.create_sheet("Wrapper Views")

    headers = [
        "Measure Name", "Fact Table", "Pattern", "Sub-Type",
        "Original DAX", "Wrapper SQL", "Status", "Score", "Tier"
    ]
    thin = Side(style="thin", color="CCCCCC")
    border = Border(bottom=thin)
    hfont = Font(bold=True, size=11, color="FFFFFF")
    hfill = PatternFill(start_color="548235", end_color="548235", fill_type="solid")
    wrap = Alignment(wrap_text=True, vertical="top")
    top = Alignment(vertical="top")

    ws.append(headers)
    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=ci)
        cell.font = hfont
        cell.fill = hfill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in rows:
        ws.append(row)

    for ri in range(2, ws.max_row + 1):
        for ci in range(1, ws.max_column + 1):
            cell = ws.cell(row=ri, column=ci)
            cell.alignment = wrap if ci in (5, 6) else top
            cell.border = border

    for ci in range(1, ws.max_column + 1):
        max_len = max((len(str(ws.cell(row=r, column=ci).value or "")[:60])
                       for r in range(1, min(ws.max_row + 1, 50))), default=10)
        ws.column_dimensions[ws.cell(row=1, column=ci).column_letter].width = min(max(max_len + 2, 12), 50)

    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"
    wb.save(xlsx_path)
    wrapped = sum(1 for r in rows if r[6] == "WRAPPED")
    skipped = sum(1 for r in rows if "SKIPPED" in str(r[5]))
    print(f"conversion_details.xlsx: added 'Wrapper Views' sheet ({wrapped} wrapped, {skipped} skipped)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    a = ap.parse_args()
    wd = a.workdir
    model = load_json(os.path.join(wd, "model.json"), "model.json")
    tr = load_json(os.path.join(wd, "translations.json"), "translations.json")
    tm = load_json(os.path.join(wd, "table_map.json"), "table_map.json")
    cls_path = os.path.join(wd, "classification.json")
    cls = load_json(cls_path, "classification.json") if os.path.exists(cls_path) else {"measures": {}}
    build_wrappers(wd, model, tr, cls, tm)


if __name__ == "__main__":
    main()
