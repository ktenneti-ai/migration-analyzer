#!/usr/bin/env python3
"""Stage 1 — Extract a Power BI / Tabular model into model.json.

Inputs (one of):
  --bim model.bim | model.json     TOM JSON export (Tabular Editor: Save to file)
  --tmdl <folder>                  pbip / TMDL folder (best-effort parse)
  --xmla <server> --db <name>      live XMLA endpoint (wire to pyadomd/AMO/TE CLI)

Everything downstream is grounded here. Never reconstruct a model from a
dashboard description.

Usage: python extract_model.py --bim model.bim --workdir conversion/sales
"""
import argparse, json, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from _shared import save_json


def extract_from_bim(path: str) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        raw = json.load(f)
    # Handle .bim (direct model), XMLA createOrReplace wrapper, or raw model JSON
    if "createOrReplace" in raw:
        model = raw["createOrReplace"].get("database", {}).get("model", {})
    elif "create" in raw:
        model = raw["create"].get("database", {}).get("model", {})
    else:
        model = raw.get("model", raw)
    tables, calc_tables = [], []
    for t in model.get("tables", []):
        cols, calc_cols, hiers = [], [], []
        for c in t.get("columns", []):
            entry = {"name": c["name"], "dataType": c.get("dataType"),
                     "isHidden": c.get("isHidden", False)}
            if c.get("type") == "calculated" or c.get("expression"):
                entry["expression"] = _expr(c.get("expression"))
                calc_cols.append(entry)
            else:
                cols.append(entry)
        for h in t.get("hierarchies", []):
            hiers.append({"name": h["name"],
                          "levels": [l["column"] for l in h.get("levels", [])]})
        measures = [{"name": m["name"], "dax": _expr(m["expression"]),
                     "displayFolder": m.get("displayFolder"),
                     "formatString": m.get("formatString"),
                     "description": m.get("description")}
                    for m in t.get("measures", [])]
        src_hint = None
        for p in t.get("partitions", []):
            src = p.get("source", {})
            if src.get("type") == "calculated":
                calc_tables.append({"name": t["name"], "expression": _expr(src.get("expression"))})
            src_hint = src_hint or _expr(src.get("expression"))
        tables.append({"name": t["name"], "columns": cols, "calculatedColumns": calc_cols,
                       "hierarchies": hiers, "measures": measures,
                       "isHidden": t.get("isHidden", False), "source_hint": src_hint,
                       "description": t.get("description")})
    relationships = [{
        "from_table": r.get("fromTable"), "from_column": r.get("fromColumn"),
        "to_table": r.get("toTable"), "to_column": r.get("toColumn"),
        "cross_filter": r.get("crossFilteringBehavior", "oneDirection"),
        "is_active": r.get("isActive", True),
        "from_cardinality": r.get("fromCardinality", "many"),
        "to_cardinality": r.get("toCardinality", "one"),
    } for r in model.get("relationships", [])]
    roles = [{"name": ro["name"],
              "tablePermissions": [{"table": tp.get("name"),
                                    "filterExpression": _expr(tp.get("filterExpression"))}
                                   for tp in ro.get("tablePermissions", [])]}
             for ro in model.get("roles", [])]
    calc_groups = []
    for t in model.get("tables", []):
        cg = t.get("calculationGroup")
        if cg:
            calc_groups.append({"table": t["name"],
                                "items": [{"name": i["name"],
                                           "expression": _expr(i.get("calculationItem", {}).get("expression") or i.get("expression"))}
                                          for i in cg.get("calculationItems", [])]})
    out = {"name": model.get("name") or os.path.basename(path),
           "tables": tables, "relationships": relationships,
           "features": {
               "roles_rls": roles,
               "calculation_groups": calc_groups,
               "calculated_tables": calc_tables,
               "bidirectional_relationships": [r for r in relationships
                                               if r["cross_filter"].lower().startswith("both")],
               "inactive_relationships": [r for r in relationships if not r["is_active"]],
               "m2m_relationships": [r for r in relationships
                                     if r["from_cardinality"] == "many" and r["to_cardinality"] == "many"],
               "perspectives": [p.get("name") for p in model.get("perspectives", [])],
               "cultures": [c.get("name") for c in model.get("cultures", [])],
           }}
    return out


def _expr(e):
    if e is None:
        return None
    return "\n".join(e) if isinstance(e, list) else str(e)


def extract_from_tmdl(folder: str) -> dict:
    """Best-effort TMDL parse: measures + relationships. Prefer a .bim export
    for full fidelity (TMDL regex loses dtypes, calc cols, hierarchies, RLS)."""
    tables, rels = [], []
    defs = os.path.join(folder, "definition") if os.path.isdir(os.path.join(folder, "definition")) else folder
    tdir = os.path.join(defs, "tables")
    if os.path.isdir(tdir):
        for fn in sorted(os.listdir(tdir)):
            if not fn.endswith(".tmdl"):
                continue
            with open(os.path.join(tdir, fn), encoding="utf-8") as f:
                text = f.read()
            tname = re.search(r"^table\s+(?:'([^']+)'|(\S+))", text, re.M)
            tname = (tname.group(1) or tname.group(2)) if tname else fn[:-5]
            measures = [{"name": m[0] or m[1], "dax": m[2].strip()}
                        for m in re.findall(r"^\tmeasure\s+(?:'([^']+)'|([^=\s']+))\s*=\s*((?:.|\n(?=\t\t))*)", text, re.M)]
            columns = [{"name": c[0] or c[1]} for c in re.findall(r"^\tcolumn\s+(?:'([^']+)'|(\S+))", text, re.M)]
            tables.append({"name": tname, "columns": columns, "calculatedColumns": [],
                           "hierarchies": [], "measures": measures, "source_hint": None})
    rfile = os.path.join(defs, "relationships.tmdl")
    if os.path.exists(rfile):
        with open(rfile, encoding="utf-8") as f:
            text = f.read()
        for block in re.split(r"^relationship\s+", text, flags=re.M)[1:]:
            fr = re.search(r"fromColumn:\s*(?:'([^']+)'|(\S+))\.(?:'([^']+)'|(\S+))", block)
            to = re.search(r"toColumn:\s*(?:'([^']+)'|(\S+))\.(?:'([^']+)'|(\S+))", block)
            if fr and to:
                rels.append({"from_table": fr.group(1) or fr.group(2), "from_column": fr.group(3) or fr.group(4),
                             "to_table": to.group(1) or to.group(2), "to_column": to.group(3) or to.group(4),
                             "cross_filter": "bothDirections" if "crossFilteringBehavior: bothDirections" in block else "oneDirection",
                             "is_active": "isActive: false" not in block,
                             "from_cardinality": "many", "to_cardinality": "one"})
    return {"name": os.path.basename(folder), "tables": tables, "relationships": rels,
            "features": {"roles_rls": [], "calculation_groups": [], "calculated_tables": [],
                         "bidirectional_relationships": [r for r in rels if r["cross_filter"] != "oneDirection"],
                         "inactive_relationships": [r for r in rels if not r["is_active"]],
                         "m2m_relationships": [], "perspectives": [], "cultures": [],
                         "tmdl_best_effort": True}}


def extract_from_xmla(server: str, database: str) -> dict:
    raise NotImplementedError(
        "Wire to your XMLA client (pyadomd / Tabular Editor CLI / AMO). Read-only, "
        "member+ access. Return the same shape as extract_from_bim. Fallback: ask "
        "for a .bim export.")


def validate_integrity(model: dict) -> tuple:
    """Cross-check the extraction before anything downstream trusts it.
    Returns (fatal_errors, warnings)."""
    fatal, warn = [], []
    tables = model.get("tables", [])
    if not tables:
        fatal.append("no tables extracted — check the .bim/TMDL source or extractor mapping")
    names = [t["name"] for t in tables]
    for dup in {n for n in names if names.count(n) > 1}:
        fatal.append(f"duplicate table name '{dup}' — extraction is ambiguous")
    all_measure_names = [m["name"] for t in tables for m in t.get("measures", [])]
    for dup in {n for n in all_measure_names if all_measure_names.count(n) > 1}:
        fatal.append(f"duplicate measure name '{dup}' across tables — DAX inventory "
                     "cannot disambiguate references to it")
    n_empty_dax = sum(1 for t in tables for m in t.get("measures", [])
                      if not (m.get("dax") or "").strip())
    if n_empty_dax:
        fatal.append(f"{n_empty_dax} measure(s) have an empty DAX expression — "
                     "the export is likely truncated or malformed")
    table_set = set(names)
    for r in model.get("relationships", []):
        for side in ("from_table", "to_table"):
            if r.get(side) and r[side] not in table_set:
                warn.append(f"relationship references unknown table '{r[side]}' "
                           f"({r.get('from_table')} -> {r.get('to_table')})")
    n_no_cols = sum(1 for t in tables if not t.get("columns") and not t.get("measures"))
    if n_no_cols:
        warn.append(f"{n_no_cols} table(s) have neither columns nor measures — "
                   "likely a calculated/hidden table or an extraction gap; confirm")
    return fatal, warn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bim"); ap.add_argument("--tmdl")
    ap.add_argument("--xmla"); ap.add_argument("--db")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero on FATAL integrity errors instead of just warning")
    a = ap.parse_args()
    if a.bim:
        model = extract_from_bim(a.bim)
    elif a.tmdl:
        model = extract_from_tmdl(a.tmdl)
    elif a.xmla:
        model = extract_from_xmla(a.xmla, a.db)
    else:
        sys.exit("Provide --bim, --tmdl, or --xmla")

    fatal, warn = validate_integrity(model)
    if fatal:
        print("FATAL integrity errors (see also model-coverage.md / source-table-analysis.md):")
        for f in fatal:
            print(f"  FATAL: {f}")
        if a.strict:
            sys.exit("Aborting (--strict): fix the export and re-extract before "
                      "trusting anything downstream.")
    for w in warn:
        print(f"  WARNING: {w}")

    os.makedirs(a.workdir, exist_ok=True)
    out = os.path.join(a.workdir, "model.json")
    save_json(model, out)
    n_meas = sum(len(t["measures"]) for t in model["tables"])
    f = model["features"]
    print(f"model.json: {len(model['tables'])} tables, {len(model['relationships'])} relationships, {n_meas} measures")
    print(f"  measure names (exhaustive, cross-check against the PBI model before proceeding): "
          f"{sorted(m['name'] for t in model['tables'] for m in t['measures'])}")
    for k in ("calculation_groups", "bidirectional_relationships", "m2m_relationships",
              "inactive_relationships", "roles_rls", "calculated_tables"):
        if f.get(k):
            print(f"  FEATURE PRESENT -> {k}: {len(f[k])} (see model-coverage.md)")
    if model.get("features", {}).get("tmdl_best_effort"):
        print("  ⚠️  TMDL best-effort parse — dtypes, calc columns, hierarchies, and RLS "
              "are not extracted. Re-export as .bim for full fidelity.")


if __name__ == "__main__":
    main()
