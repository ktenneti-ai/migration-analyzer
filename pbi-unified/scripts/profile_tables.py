#!/usr/bin/env python3
"""Stage 2.5 — Source table profiling & gap analysis (PBI model vs Unity Catalog).

Never write a join/measure against a table or column you haven't verified exists,
with a compatible type, in the target catalog. See references/source-table-analysis.md.

Inputs:
  model.json                 (from extract_model.py — required)
  --catalog-scan <json>      offline scan from information_schema queries
  --live --catalog X          stub: wire databricks-sql-connector
  --table-map-seed <json>    optional partial table_map.json already confirmed by human

Outputs:
  profile.json, table_map.json, missing_tables.sql, gap_report.md

Usage: python profile_tables.py --workdir conversion/sales --catalog-scan scan.json
"""
import argparse, datetime, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from _shared import snake, load_json, save_json, save_text

PBI_TO_SPARK = {
    "int64": "bigint", "double": "double", "decimal": "decimal(38,10)",
    "currency": "decimal(19,4)", "dateTime": "timestamp", "date": "date",
    "string": "string", "boolean": "boolean", "binary": "binary",
}
NUMERIC_SPARK = {"bigint", "int", "double", "float", "decimal"}
STRINGY_SPARK = {"string", "varchar"}
DATEY_SPARK = {"date", "timestamp"}

NUMERIC_RE = re.compile(r"^\s*-?\$?\s*\d{1,3}(,\d{3})*(\.\d+)?\s*%?\s*$")
DATE_RE = re.compile(
    r"^\s*\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?\s*$|^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$")


def spark_base_type(t):
    t = (t or "").lower()
    if t.startswith("decimal"):
        return "decimal"
    for base in ("bigint", "int", "smallint", "tinyint", "double", "float",
                 "string", "varchar", "date", "timestamp", "boolean", "binary"):
        if t.startswith(base):
            return base
    return t


def match_physical_table(pbi_name, catalog_tables, seed_physical):
    if pbi_name in seed_physical:
        return seed_physical[pbi_name], "seeded"
    target = snake(pbi_name)
    for full in catalog_tables:
        leaf = full.split(".")[-1]
        if snake(leaf) == target:
            return full, "exact_name_match"
    for full in catalog_tables:
        leaf = snake(full.split(".")[-1])
        if target in leaf or leaf in target:
            return full, "fuzzy_name_match"
    return None, "no_match"


def sample_looks_numeric(values):
    vals = [v for v in values if v not in (None, "")]
    if not vals:
        return False
    hits = sum(1 for v in vals if NUMERIC_RE.match(str(v)))
    return hits / len(vals) >= 0.8


def sample_looks_datey(values):
    vals = [v for v in values if v not in (None, "")]
    if not vals:
        return False
    hits = sum(1 for v in vals if DATE_RE.match(str(v)))
    return hits / len(vals) >= 0.8


def reconcile_columns(pbi_table, phys_table, catalog_by_name):
    phys = catalog_by_name.get(phys_table, {})
    phys_cols = {snake(c["name"]): c for c in phys.get("columns", [])}
    sample = phys.get("sample", [])
    out = {"matched": [], "missing_in_catalog": [], "dtype_flags": []}
    all_pbi_cols = (pbi_table.get("columns", []) + pbi_table.get("calculatedColumns", []))
    for c in all_pbi_cols:
        key = snake(c["name"])
        if key not in phys_cols:
            out["missing_in_catalog"].append(c["name"])
            continue
        phys_c = phys_cols[key]
        base = spark_base_type(phys_c.get("type"))
        pbi_type = (c.get("dataType") or "").lower()
        entry = {"pbi_column": c["name"], "physical_column": phys_c["name"],
                 "physical_type": phys_c.get("type")}
        out["matched"].append(entry)
        sample_vals = [row.get(phys_c["name"]) for row in sample if phys_c["name"] in row]
        if base in STRINGY_SPARK and pbi_type in ("int64", "double", "decimal", "currency"):
            confirmed = sample_looks_numeric(sample_vals) if sample_vals else None
            out["dtype_flags"].append({
                "column": c["name"], "issue": "varchar_numeric",
                "detail": f"PBI type {pbi_type} but Unity Catalog column is {phys_c.get('type')}",
                "sample_confirms": confirmed,
                "fix": f"try_cast({phys_c['name']} as {PBI_TO_SPARK.get(pbi_type, 'double')})"})
        if base in STRINGY_SPARK and pbi_type in ("datetime", "date"):
            confirmed = sample_looks_datey(sample_vals) if sample_vals else None
            out["dtype_flags"].append({
                "column": c["name"], "issue": "string_date",
                "detail": f"PBI type {pbi_type} but Unity Catalog column is {phys_c.get('type')}",
                "sample_confirms": confirmed,
                "fix": f"to_date({phys_c['name']})  -- or to_timestamp() if time-of-day matters"})
    return out


def ctas_for_missing(pbi_table, physical_hint):
    cols = []
    for c in pbi_table.get("columns", []):
        spark_t = PBI_TO_SPARK.get((c.get("dataType") or "").lower(), "string")
        cols.append(f"  {snake(c['name'])} {spark_t}")
    body = ",\n".join(cols) or "  -- no non-hidden columns found in model.json"
    return (f"-- PBI table '{pbi_table['name']}' has no Unity Catalog match.\n"
            f"-- Confirm the real target name before running; this is a starting point only.\n"
            f"CREATE TABLE IF NOT EXISTS {physical_hint} (\n{body}\n) USING DELTA;\n"
            f"-- Then land data, e.g.:\n"
            f"-- COPY INTO {physical_hint} FROM '<landing_path>' FILEFORMAT = CSV "
            f"FORMAT_OPTIONS ('header'='true','inferSchema'='true');\n"
            f"-- or an Auto Loader stream for continuous ingestion.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--catalog-scan")
    ap.add_argument("--table-map-seed")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--catalog"); ap.add_argument("--schema")
    a = ap.parse_args()
    wd = a.workdir
    model = load_json(os.path.join(wd, "model.json"), "model.json")

    if a.live:
        raise NotImplementedError(
            "Wire databricks-sql-connector: run information_schema.tables / "
            ".columns for --catalog/--schema, plus `SELECT * ... LIMIT 20` and "
            "`SELECT count(*) ...` per table. Fallback: run the queries in "
            "references/source-table-analysis.md by hand and pass --catalog-scan.")

    scan = {"tables": []}
    if a.catalog_scan:
        scan = load_json(a.catalog_scan, "catalog-scan")
    catalog_by_name = {t["name"]: t for t in scan["tables"]}
    catalog_names = list(catalog_by_name)

    seed = {"physical": {}, "aliases": {}}
    tm_path = os.path.join(wd, "table_map.json")
    if a.table_map_seed:
        seed.update(load_json(a.table_map_seed, "table-map-seed"))
    elif os.path.exists(tm_path):
        seed.update(load_json(tm_path, "table_map.json"))

    profile = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
               "catalog_scan_provided": bool(a.catalog_scan), "tables": {}}
    missing_sql, gap_lines = [], []
    merged_physical = dict(seed.get("physical", {}))

    for t in model["tables"]:
        if t.get("isHidden"):
            continue
        phys, how = match_physical_table(t["name"], catalog_names, seed.get("physical", {}))
        entry = {"pbi_table": t["name"], "physical_table": phys, "match_method": how}
        if phys:
            merged_physical.setdefault(t["name"], phys)
            phys_info = catalog_by_name.get(phys, {})
            entry["row_count"] = phys_info.get("row_count")
            entry["sample_rows_available"] = len(phys_info.get("sample", []))
            entry["column_reconciliation"] = reconcile_columns(t, phys, catalog_by_name)
            n_missing = len(entry["column_reconciliation"]["missing_in_catalog"])
            n_flags = len(entry["column_reconciliation"]["dtype_flags"])
            if n_missing:
                gap_lines.append(f"- [HIGH] `{t['name']}` -> `{phys}`: "
                                 f"{n_missing} PBI column(s) not found in Unity Catalog: "
                                 + ", ".join(entry["column_reconciliation"]["missing_in_catalog"]))
            if n_flags:
                for fl in entry["column_reconciliation"]["dtype_flags"]:
                    gap_lines.append(f"- [MEDIUM] `{t['name']}.{fl['column']}`: {fl['issue']} — "
                                     f"{fl['detail']}. Fix: `{fl['fix']}`")
        else:
            physical_hint = f"<catalog>.<schema>.{snake(t['name'])}"
            entry["gap"] = "table not found in provided catalog scan"
            missing_sql.append(ctas_for_missing(t, physical_hint))
            gap_lines.insert(0, f"- [BLOCKER] `{t['name']}`: no Unity Catalog match — "
                             "cannot join or aggregate until this is resolved "
                             "(see missing_tables.sql)")
        profile["tables"][t["name"]] = entry

    save_json(profile, os.path.join(wd, "profile.json"))
    tm_out = dict(seed)
    tm_out["physical"] = merged_physical
    save_json(tm_out, tm_path)
    save_text("\n\n".join(missing_sql), os.path.join(wd, "missing_tables.sql"))

    matched = sum(1 for e in profile["tables"].values() if e.get("physical_table"))
    total = len(profile["tables"])
    lines = [f"# Source Table Gap Report — {model['name']}",
             f"_Generated {profile['generated_at']}_", "",
             f"**{matched}/{total} PBI tables matched to a Unity Catalog table.**", ""]
    if not a.catalog_scan:
        lines.append("⚠️ No `--catalog-scan` provided — matches above are by name only "
                     "(unverified). Run the queries in "
                     "`references/source-table-analysis.md` and re-run with "
                     "`--catalog-scan` before trusting this report or writing DDL.")
        lines.append("")
    lines.append("## Gaps (severity-ranked)")
    lines += gap_lines if gap_lines else ["None — every table matched with no dtype flags."]
    save_text("\n".join(lines), os.path.join(wd, "gap_report.md"))

    print(f"profile.json: {matched}/{total} tables matched"
          f"{' (scan provided)' if a.catalog_scan else ' (NAME-ONLY, unverified — provide --catalog-scan)'}")
    print(f"table_map.json: physical mapping filled for {len(merged_physical)} table(s)")
    if missing_sql:
        print(f"missing_tables.sql: {len(missing_sql)} table(s) need CTAS + data landing before proceeding")
    if gap_lines:
        print(f"gap_report.md: {len(gap_lines)} gap(s) — read before build_view.py")


if __name__ == "__main__":
    main()
