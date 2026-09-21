#!/usr/bin/env python3
"""Stage 2 — Function inventory, reference extraction, measure dependency graph.

Reads model.json, writes inventory.json:
  per measure: functions used, table/column refs, referenced measures, VAR usage,
  structural flags (calculate_filter_kinds, iterator_over_virtual_table, ...)
  plus a global topological order (translate leaf measures first).

Usage: python dax_inventory.py --workdir conversion/sales
"""
import argparse, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from _shared import load_json, save_json, split_args

FUNC_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
COLREF_RE = re.compile(r"(?:'([^']+)'|(\b[A-Za-z_]\w*))\s*\[([^\]\[]+)\]")
MEASREF_RE = re.compile(r"(?<![\w'\]])\[([^\]\[]+)\]")


def strip_strings_comments(dax: str) -> str:
    dax = re.sub(r"//[^\n]*|--[^\n]*", " ", dax)
    dax = re.sub(r"/\*.*?\*/", " ", dax, flags=re.S)
    return re.sub(r'"(?:[^"]|"")*"', '""', dax)


def analyze(dax: str, measure_names: set, table_names: set) -> dict:
    s = strip_strings_comments(dax or "")
    funcs = {f.upper() for f in FUNC_RE.findall(s)}
    cols, tables = [], set()
    for m in COLREF_RE.finditer(s):
        t = (m.group(1) or m.group(2) or "").strip()
        if t and (t in table_names or t.lower() in {x.lower() for x in table_names}):
            tables.add(t)
            cols.append({"table": t, "column": m.group(3).strip()})
    meas_refs = sorted({m.group(1).strip() for m in MEASREF_RE.finditer(s)
                        if m.group(1).strip() in measure_names})
    calc_args = _calculate_filter_kinds(s)
    return {
        "functions": sorted(funcs),
        "tables": sorted(tables),
        "columns": cols,
        "measure_refs": meas_refs,
        "uses_var": bool(re.search(r"\bVAR\b", s, re.I)),
        "var_count": len(re.findall(r"\bVAR\b", s, re.I)),
        "calculate_filter_kinds": calc_args,
        "iterator_over_virtual_table": _iterator_virtual(s),
        "blank_zero_sensitive": bool(re.search(r"BLANK\s*\(\s*\)\s*(=|<>)|(=|<>)\s*0\b.*ISBLANK|ISBLANK.*(=|<>)", s, re.I)),
    }


def _calculate_filter_kinds(s: str) -> list:
    kinds = set()
    for m in re.finditer(r"\bCALCULATE(?:TABLE)?\s*\(", s, re.I):
        args, _ = split_args(s, m.end() - 1)
        for arg in args[1:]:
            a = arg.strip()
            if re.match(r"^(ALL|ALLEXCEPT|REMOVEFILTERS)\s*\(", a, re.I):
                kinds.add("all_family")
            elif re.match(r"^KEEPFILTERS\s*\(", a, re.I):
                kinds.add("keepfilters")
            elif re.match(r"^(USERELATIONSHIP|CROSSFILTER|TREATAS)\s*\(", a, re.I):
                kinds.add("relationship_mod")
            elif re.match(r"^FILTER\s*\(", a, re.I):
                kinds.add("filter_table")
            elif re.search(r"\bIN\s*\{|=|<>|>=|<=|>|<", a):
                kinds.add("boolean")
            else:
                kinds.add("other")
    return sorted(kinds)


def _iterator_virtual(s: str) -> bool:
    for m in re.finditer(r"\b(SUMX|AVERAGEX|MINX|MAXX|COUNTX|CONCATENATEX|RANKX)\s*\(", s, re.I):
        args, _ = split_args(s, m.end() - 1)
        if args and re.match(r"^\s*(FILTER|VALUES|ALL|ADDCOLUMNS|SUMMARIZE|CROSSJOIN|GENERATE|TOPN|DISTINCT)\s*\(",
                             args[0], re.I):
            return True
    return False


def topo_order(deps: dict) -> tuple:
    order, temp, perm, cycles = [], set(), set(), []
    def visit(n, stack):
        if n in perm:
            return
        if n in temp:
            cycles.append(stack + [n])
            return
        temp.add(n)
        for d in deps.get(n, []):
            visit(d, stack + [n])
        temp.discard(n)
        perm.add(n)
        order.append(n)
    for n in deps:
        visit(n, [])
    return order, cycles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    a = ap.parse_args()
    model = load_json(os.path.join(a.workdir, "model.json"), "model.json")
    table_names = {t["name"] for t in model["tables"]}
    all_measures = {m["name"]: m for t in model["tables"] for m in t["measures"]}
    inv, deps = {}, {}
    for t in model["tables"]:
        for m in t["measures"]:
            info = analyze(m["dax"], set(all_measures), table_names)
            info["home_table"] = t["name"]
            inv[m["name"]] = info
            deps[m["name"]] = info["measure_refs"]
    order, cycles = topo_order(deps)
    out = {"measures": inv, "topological_order": order, "cycles": cycles}
    save_json(out, os.path.join(a.workdir, "inventory.json"))
    print(f"inventory.json: {len(inv)} measures, {len(cycles)} dependency cycles")
    if cycles:
        print("  CYCLES (forced MANUAL_PORT):", cycles)


if __name__ == "__main__":
    main()
