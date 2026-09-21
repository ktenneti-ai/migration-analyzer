#!/usr/bin/env python3
"""Stage 4 — Tiered DAX -> Spark SQL translation + change-request application.

Reads model.json + inventory.json + classification.json, writes translations.json:
  per measure: {sql, status, tier, notes[], original_dax}
T1 mechanical, T2 pattern, T3 template with -- REVIEW markers, T4 stub.
The generating assistant refines T2/T3 SQL by hand *in translations.json* (that's
expected — this script produces the honest baseline + markers, not magic).

Change-request mode (reviewer loop):
  python translate.py --apply-change-request change_request.json --workdir <wd>

Usage: python translate.py --workdir conversion/sales
"""
import argparse, datetime, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from _shared import snake, split_args, load_json, save_json

DIRECT_MAP = [
    (r"\bDISTINCTCOUNTNOBLANK\s*\(", "count(distinct "),
    (r"\bDISTINCTCOUNT\s*\(", "count(distinct "),
    (r"\bCOUNTROWS\s*\(\s*'?[^)']*'?\s*\)", "count(*)"),
    (r"\bSUM\s*\(", "sum("), (r"\bAVERAGE\s*\(", "avg("),
    (r"\bMIN\s*\(", "min("), (r"\bMAX\s*\(", "max("),
    (r"\bCOUNTA?\s*\(", "count("),
    (r"\bBLANK\s*\(\s*\)", "NULL"),
    (r"\bTODAY\s*\(\s*\)", "current_date()"),
    (r"\bNOW\s*\(\s*\)", "current_timestamp()"),
    # Scalar function mappings (from v1's exhaustive catalog)
    (r"\bINT\s*\(", "cast("),  # INT(x) -> cast(x as int) — assistant completes
    (r"\bTRUE\s*\(\s*\)", "true"),
    (r"\bFALSE\s*\(\s*\)", "false"),
    (r"\bYEAR\s*\(", "year("), (r"\bMONTH\s*\(", "month("),
    (r"\bDAY\s*\(", "day("), (r"\bHOUR\s*\(", "hour("),
    (r"\bMINUTE\s*\(", "minute("), (r"\bSECOND\s*\(", "second("),
    (r"\bWEEKDAY\s*\(", "dayofweek("),
    (r"\bWEEKNUM\s*\(", "weekofyear("),
    (r"\bEOMONTH\s*\(", "last_day(add_months("),  # needs closing adjustment
    (r"\bLEN\s*\(", "length("),
    (r"\bUPPER\s*\(", "upper("), (r"\bLOWER\s*\(", "lower("),
    (r"\bTRIM\s*\(", "trim("),
    (r"\bLEFT\s*\(", "left("), (r"\bRIGHT\s*\(", "right("),
    (r"\bMID\s*\(", "substring("),
    (r"\bSUBSTITUTE\s*\(", "replace("),
    (r"\bSEARCH\s*\(", "locate("),  # arg order differs — assistant adjusts
    (r"\bFIND\s*\(", "locate("),
    (r"\bCONCATENATE\s*\(", "concat("),
    (r"\bEXACT\s*\(", "-- REVIEW: EXACT -> (a = b) with case-sensitive collation\n("),
    (r"\bABS\s*\(", "abs("), (r"\bROUND\s*\(", "round("),
    (r"\bROUNDUP\s*\(", "ceil("),  # approximate
    (r"\bROUNDDOWN\s*\(", "floor("),  # approximate
    (r"\bSQRT\s*\(", "sqrt("), (r"\bEXP\s*\(", "exp("),
    (r"\bLN\s*\(", "ln("), (r"\bLOG\s*\(", "log("),
    (r"\bLOG10\s*\(", "log10("),
    (r"\bPOWER\s*\(", "power("), (r"\bMOD\s*\(", "mod("),
    (r"\bPI\s*\(\s*\)", "pi()"),
    (r"\bRAND\s*\(\s*\)", "rand()"),
    (r"\bCONVERT\s*\(", "cast("),  # assistant completes type
    (r"\bCURRENCY\s*\(", "cast("),  # assistant: cast(x as decimal(19,4))
    (r"\bUNICHAR\s*\(", "char("),
    (r"\bUNICODE\s*\(", "ascii("),  # approximate
    (r"\bREPT\s*\(", "repeat("),
    (r"\bCOMBINEVALUES\s*\(", "concat_ws("),
    (r"\bPATHITEM\s*\(", "-- REVIEW: PATHITEM -> split(path, '|')[index-1]\nsplit("),
]
COLREF_RE = re.compile(r"(?:'([^']+)'|([A-Za-z_]\w*))\s*\[([^\]\[]+)\]")


def normalize_refs(dax: str, alias_map: dict) -> str:
    """'Table'[Col] -> alias.col using alias_map {table: join_alias_or_source}."""
    def rep(m):
        t = (m.group(1) or m.group(2) or "").strip()
        col = snake(m.group(3))
        alias = alias_map.get(t, snake(t))
        return f"{alias}.{col}"
    return COLREF_RE.sub(rep, dax)


def t1(dax: str, alias_map: dict) -> str:
    s = dax
    while True:
        m = re.search(r"\bDIVIDE\s*\(", s, re.I)
        if not m:
            break
        args, end = split_args(s, m.end() - 1)
        if len(args) >= 3:
            repl = f"coalesce(try_divide({args[0].strip()}, {args[1].strip()}), {args[2].strip()})"
        elif len(args) >= 2:
            repl = f"try_divide({args[0].strip()}, {args[1].strip()})"
        else:
            break
        s = s[:m.start()] + repl + s[end + 1:]
    for pat, rep in DIRECT_MAP:
        s = re.sub(pat, rep, s, flags=re.I)
    return normalize_refs(s, alias_map).strip()


ITER_MAP = {"SUMX": "sum", "AVERAGEX": "avg", "MINX": "min", "MAXX": "max", "COUNTX": "count"}


def rewrite_calculate(s: str, notes: list) -> str:
    """CALCULATE(<agg>, <bool preds>) -> <agg> FILTER (WHERE preds) — simple case only."""
    while True:
        m = re.search(r"\bCALCULATE\s*\(", s, re.I)
        if not m:
            return s
        args, end = split_args(s, m.end() - 1)
        if len(args) < 2 or any(
                re.match(r"^\s*(ALL|ALLEXCEPT|REMOVEFILTERS|KEEPFILTERS|FILTER|USERELATIONSHIP|CROSSFILTER|TREATAS)\s*\(",
                         a, re.I) for a in args[1:]):
            return s
        preds = " AND ".join(f"({a.strip()})" for a in args[1:])
        preds = re.sub(r'"([^"]*)"', r"'\1'", preds)
        preds = re.sub(r"\bIN\s*\{([^}]*)\}", r"IN (\1)", preds, flags=re.I)
        preds = preds.replace("<>", "!=").replace("&&", " AND ").replace("||", " OR ")
        s = s[:m.start()] + f"{args[0].strip()} FILTER (WHERE {preds})" + s[end + 1:]
        notes.append("CALCULATE(agg, bool...) -> FILTER clause; verify predicates vs DAX")


def rewrite_iterators(s: str, notes: list) -> str:
    """SUMX(BareTable, expr) -> sum(expr) etc. — valid only at source grain."""
    while True:
        m = re.search(r"\b(SUMX|AVERAGEX|MINX|MAXX|COUNTX)\s*\(", s, re.I)
        if not m:
            return s
        args, end = split_args(s, m.end() - 1)
        if len(args) != 2 or re.search(r"\(", args[0]):
            return s
        s = s[:m.start()] + f"{ITER_MAP[m.group(1).upper()]}({args[1].strip()})" + s[end + 1:]
        notes.append(f"{m.group(1).upper()} over bare table -> row-expression aggregate; "
                     "valid only if view source grain == that table's grain")


def t2(dax: str, alias_map: dict, info: dict) -> tuple:
    notes, s = [], dax
    s = re.sub(r"\bISBLANK\s*\(([^()]+)\)", r"(\1 IS NULL)", s, flags=re.I)
    s = re.sub(r"\bCOALESCE\s*\(", "coalesce(", s, flags=re.I)
    s = rewrite_calculate(s, notes)
    s = rewrite_iterators(s, notes)
    if re.search(r"\bIF\s*\(", s, re.I):
        notes.append("IF -> CASE WHEN: assistant rewrites; verify ELSE NULL semantics")
    if re.search(r"\bSWITCH\s*\(", s, re.I):
        notes.append("SWITCH -> CASE: assistant rewrites")
    if info.get("uses_var"):
        notes.append("VAR/RETURN -> inline subexpressions or decompose into helper measures")
    return t1(s, alias_map), notes


TIME_TEMPLATE = """-- REVIEW: time intelligence — requires explicit dim_date with period columns.
-- Pattern A (period-shifted measure, e.g. 'X LY'): add join alias
--   date_ly ON date_ly.date_key = <date_dim>.date_key_ly  and aggregate over it.
-- Pattern B (to-date): FILTER (WHERE <date_dim>.is_current_ytd) or precomputed flag.
-- Choose pattern with reviewer; the anchor date is query context in PBI and must be
-- made explicit here."""

ALL_TEMPLATE = """-- REVIEW: ALL/REMOVEFILTERS = ratio-of-total semantics. Metric View measures are
-- plain aggregates; implement as measure pair (numerator here, denominator as its own
-- measure) and compute the ratio in the consuming query with MEASURE(), or via a
-- companion view. Do not embed window functions in the view."""


def t3(dax: str, alias_map: dict, info: dict, reasons: list) -> tuple:
    header = []
    fs = set(info.get("functions", []))
    if fs & {"SAMEPERIODLASTYEAR","DATESYTD","DATEADD","PARALLELPERIOD","TOTALYTD",
             "TOTALQTD","TOTALMTD","DATESINPERIOD","DATESBETWEEN"} or \
       any("time intelligence" in r for r in reasons):
        header.append(TIME_TEMPLATE)
    if fs & {"ALL","ALLEXCEPT","REMOVEFILTERS","ALLSELECTED"}:
        header.append(ALL_TEMPLATE)
    if "LOOKUPVALUE" in fs:
        header.append("-- REVIEW: LOOKUPVALUE -> add explicit join in joins: block, reference alias.col")
    if info.get("iterator_over_virtual_table"):
        header.append("-- REVIEW: iterator over virtual table -> pre-aggregated table/CTE (see optimization-guide #1)")
    body, notes = t2(dax, alias_map, info)
    return "\n".join(header + [f"-- CANDIDATE (verify): {body}"]), notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--apply-change-request")
    a = ap.parse_args()
    wd = a.workdir
    tpath = os.path.join(wd, "translations.json")

    if a.apply_change_request:
        cr = load_json(a.apply_change_request, "change_request.json")
        tr = load_json(tpath, "translations.json")
        applied = []
        for item in cr.get("changes", []):
            m = item["measure"]
            if m not in tr["measures"]:
                continue
            if item.get("new_sql"):
                tr["measures"][m]["sql"] = item["new_sql"]
                tr["measures"][m]["status"] = item.get("new_status", "reviewed")
            if item.get("action") == "drop":
                tr["measures"][m]["status"] = "dropped"
            tr["measures"][m].setdefault("notes", []).append(
                f"change_request: {item.get('reason','')}")
            applied.append(m)
        tr.setdefault("revisions", []).append({
            "at": datetime.datetime.now().isoformat(timespec="seconds"),
            "source": a.apply_change_request, "applied": applied,
            "reviewer": cr.get("reviewer", "pbi-unified-reviewer")})
        save_json(tr, tpath)
        print(f"applied {len(applied)} changes; revision {len(tr['revisions'])}")
        return

    model = load_json(os.path.join(wd, "model.json"), "model.json")
    inv = load_json(os.path.join(wd, "inventory.json"), "inventory.json")
    cls = load_json(os.path.join(wd, "classification.json"), "classification.json")
    alias_map = {}
    fact_names = set()
    tm_path = os.path.join(wd, "table_map.json")
    if os.path.exists(tm_path):
        tm_early = load_json(tm_path, "table_map.json")
        alias_map = dict(tm_early.get("aliases", {}))
        if tm_early.get("fact"):
            alias_map.setdefault(tm_early["fact"], "source")
        for fg in tm_early.get("fact_groups", []):
            fact_names.add(fg["name"])
        if not fact_names and tm_early.get("fact"):
            fact_names.add(tm_early["fact"])
    dax_by_name = {m["name"]: m["dax"] for t in model["tables"] for m in t["measures"]}
    measure_home_table = {}
    for t in model["tables"]:
        for m in t.get("measures", []):
            measure_home_table[m["name"]] = t["name"]

    dim_prefix_re = re.compile(r"^(dim|d_|dimension|lookup|date|calendar)", re.I)
    true_fact_names = {n for n in fact_names
                       if not dim_prefix_re.match(n.lower().replace("-", "").replace("_", "").replace(" ", ""))}

    AGG_COL_RE = re.compile(
        r"\b(?:SUM|SUMX|AVERAGE|AVERAGEX|COUNT|COUNTA?|COUNTX|"
        r"DISTINCTCOUNT|DISTINCTCOUNTNOBLANK|MIN|MINX|MAX|MAXX)\s*\(\s*"
        r"(?:'([^']+)'|([A-Za-z_]\w*))\s*\[", re.I)
    COUNTROWS_RE = re.compile(
        r"\bCOUNTROWS\s*\(\s*(?:'([^']+)'|([A-Za-z_]\w*))\s*\)", re.I)

    def detect_fact_group(dax_str, tables_list, measure_name=None):
        """Determine which fact table a measure primarily aggregates.
        Prefers the PBI home table if it's a real fact, then DAX agg target,
        then falls back to any fact_group match."""
        from collections import Counter as C
        home = measure_home_table.get(measure_name)
        if home and home in true_fact_names:
            return home
        agg_tables = C()
        for m in AGG_COL_RE.finditer(dax_str):
            ref = (m.group(1) or m.group(2) or "").strip()
            if ref in true_fact_names:
                agg_tables[ref] += 2
            elif ref in fact_names:
                agg_tables[ref] += 1
        for m in COUNTROWS_RE.finditer(dax_str):
            ref = (m.group(1) or m.group(2) or "").strip()
            if ref in true_fact_names:
                agg_tables[ref] += 2
            elif ref in fact_names:
                agg_tables[ref] += 1
        if agg_tables:
            best = agg_tables.most_common(1)[0][0]
            if best in true_fact_names:
                return best
            second_choices = [(t, c) for t, c in agg_tables.items() if t in true_fact_names]
            if second_choices:
                return max(second_choices, key=lambda x: x[1])[0]
            return best
        for t in (tables_list or []):
            if t in true_fact_names:
                return t
        for t in (tables_list or []):
            if t in fact_names:
                return t
        return None

    out = {"measures": {}, "revisions": []}
    for name in inv["topological_order"]:
        info, c = inv["measures"][name], cls["measures"][name]
        dax = dax_by_name.get(name, "")
        if c["band"] == "AUTO":
            sql, notes, status = t1(dax, alias_map), [], "auto"
        elif c["band"] == "AUTO_SPOT_CHECK":
            sql, notes = t2(dax, alias_map, info)
            status = "auto_spot_check"
        elif c["band"] == "NEEDS_REVIEW":
            sql, notes = t3(dax, alias_map, info, c["reasons"])
            status = "needs_review"
        elif c["band"] == "MANUAL_PORT":
            sql, notes, status = ("-- TODO: manual port required (see reasons in classification.json)",
                                  [], "manual_port")
        else:
            sql, notes, status = ("-- UNSUPPORTED in Metric View (see model-coverage.md, RLS section)",
                                  [], "unsupported")
        for dep in info.get("measure_refs", []):
            d = out["measures"].get(dep)
            if d and d["status"] in ("auto", "auto_spot_check", "reviewed"):
                sql = sql.replace(f"[{dep}]", f"MEASURE({dep})")
            elif f"[{dep}]" in sql:
                notes = notes + [f"unresolved measure ref [{dep}] ({d['status'] if d else 'missing'}) — resolve manually"]
                if status in ("auto", "auto_spot_check"):
                    status = "needs_review"
        fg = detect_fact_group(dax, info.get("tables", []), measure_name=name)
        if fg is None:
            for dep in info.get("measure_refs", []):
                d = out["measures"].get(dep)
                if d and d.get("fact_group"):
                    fg = d["fact_group"]
                    break
        if fg is None and fact_names:
            fg = tm_early.get("fact")
        out["measures"][name] = {
            "original_dax": dax, "sql": sql, "status": status,
            "tier": c["tier"], "score": c["score"], "category": c["category"],
            "notes": notes, "fact_group": fg}
    save_json(out, tpath)
    counts = {}
    for m in out["measures"].values():
        counts[m["status"]] = counts.get(m["status"], 0) + 1
    print(f"translations.json: {counts}")
    print("NOTE: refine T2/T3 SQL in translations.json before build_view.py — the "
          "assistant rewrites IF/SWITCH/CALCULATE bodies per dax-translation-catalog.md.")


if __name__ == "__main__":
    main()
