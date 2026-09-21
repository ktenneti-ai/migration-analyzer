#!/usr/bin/env python3
"""Stage 6 — Numeric parity harness (DAX vs Metric View) + grain checks.

Modes:
  --emit     write parity_queries/ (paired DAX + SQL per measure×slice, plus
             join grain checks) for manual execution
  --compare  read dax_results.json + sql_results.json and write parity_results.json
             (tolerance: abs<=0.01 OR rel<=1e-4)

Slices default to: grand total, plus each dimension provided via --slices.

Usage:
  python reconcile.py --workdir conversion/sales --emit --slices "Product Category"
  python reconcile.py --workdir conversion/sales --compare
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _shared import load_json, save_json, save_text

try:
    import yaml as _yaml
except ImportError:
    _yaml = None


def emit(wd, slices):
    tr = load_json(os.path.join(wd, "translations.json"), "translations.json")
    tm = load_json(os.path.join(wd, "table_map.json"), "table_map.json")
    view = tm["view_name"]
    qdir = os.path.join(wd, "parity_queries")
    os.makedirs(qdir, exist_ok=True)
    manifest = []
    testable = [n for n, m in tr["measures"].items()
                if m["status"] in ("auto", "auto_spot_check", "reviewed")]
    for name in testable:
        safe = name.replace("/", "_")
        for slc in [None] + slices:
            tag = "total" if not slc else slc.replace(" ", "_")
            dax = (f"EVALUATE\nSUMMARIZECOLUMNS(\n"
                   + (f"    '{tm.get('slice_tables',{{}}).get(slc, '?')}'[{slc}],\n" if slc else "")
                   + f"    \"val\", [{name}]\n)")
            sql = (f"SELECT {'`'+slc+'`, ' if slc else ''}MEASURE(`{name}`) AS val\n"
                   f"FROM {view}\nGROUP BY ALL\nORDER BY ALL;")
            base = os.path.join(qdir, f"{safe}__{tag}")
            save_text(dax, base + ".dax")
            save_text(sql, base + ".sql")
            manifest.append({"measure": name, "slice": slc or "total",
                             "dax": base + ".dax", "sql": base + ".sql"})

    grain = []
    spec_path = os.path.join(wd, "metric_view.yaml")
    if os.path.exists(spec_path) and _yaml:
        with open(spec_path, encoding="utf-8") as f:
            spec = _yaml.safe_load(f)
        for j in (spec.get("joins") or []):
            src = j.get("source", "")
            on_clause = j.get("on", "")
            parts = on_clause.split("=")
            if len(parts) == 2:
                dim_key = parts[1].strip()
                grain.append(f"-- fanout check: must return 0 rows\n"
                             f"SELECT {dim_key.split('.')[-1]}, count(*) c "
                             f"FROM {src} GROUP BY {dim_key.split('.')[-1]} HAVING count(*) > 1;")
    save_text("\n\n".join(grain), os.path.join(qdir, "grain_checks.sql"))
    save_json(manifest, os.path.join(qdir, "manifest.json"))
    print(f"parity_queries/: {len(manifest)} query pairs for {len(testable)} measures "
          f"+ {len(grain)} grain checks")
    print("Run DAX via XMLA/DAX Studio -> dax_results.json; SQL via Databricks -> "
          "sql_results.json. Then --compare.")


def compare(wd, abs_tol=0.01, rel_tol=1e-4):
    dax = load_json(os.path.join(wd, "dax_results.json"), "dax_results.json")
    sql = load_json(os.path.join(wd, "sql_results.json"), "sql_results.json")
    results = {}
    cls_path = os.path.join(wd, "classification.json")
    for key in sorted(set(dax) | set(sql)):
        d, s = dax.get(key), sql.get(key)
        if d is None or s is None:
            results[key] = {"status": "missing_side"}
            continue
        if "value" in d:
            dv, sv = _num(d["value"]), _num(s.get("value"))
            results[key] = _cmp_scalar(dv, sv, abs_tol, rel_tol)
        else:
            drows = {tuple(map(str, r[:-1])): _num(r[-1]) for r in d.get("rows", [])}
            srows = {tuple(map(str, r[:-1])): _num(r[-1]) for r in s.get("rows", [])}
            diffs = []
            for k in set(drows) | set(srows):
                c = _cmp_scalar(drows.get(k), srows.get(k), abs_tol, rel_tol)
                if c["status"] != "match":
                    diffs.append({"key": list(k), **c})
            results[key] = ({"status": "match", "rows": len(drows)} if not diffs
                            else {"status": "mismatch", "row_count": [len(drows), len(srows)],
                                  "diffs": diffs[:20]})
    cls = load_json(cls_path, "classification.json")
    by_measure = {}
    for key, r in results.items():
        m = key.split("|")[0]
        by_measure.setdefault(m, []).append(r["status"])
    for m, statuses in by_measure.items():
        if m not in cls["measures"]:
            continue
        c = cls["measures"][m]
        if all(s == "match" for s in statuses):
            c["parity"] = "match"
            floor = 95 if c["band"] in ("AUTO", "AUTO_SPOT_CHECK") else 80
            c["score"] = max(c["score"], floor)
        elif any(s == "mismatch" for s in statuses):
            c["parity"] = "MISMATCH"
            c["score"] = min(c["score"], 40)
            c["reasons"].append("parity mismatch — see parity_results.json")
        c["band"] = _band(c["score"])
    save_json(cls, cls_path)
    save_json(results, os.path.join(wd, "parity_results.json"))
    n_match = sum(1 for r in results.values() if r["status"] == "match")
    print(f"parity_results.json: {n_match}/{len(results)} match; classification updated")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _cmp_scalar(d, s, abs_tol, rel_tol):
    if d is None and s is None:
        return {"status": "match", "note": "both null/blank"}
    if d is None or s is None:
        return {"status": "mismatch", "dax": d, "sql": s,
                "note": "BLANK/NULL asymmetry — check blank semantics"}
    if abs(d - s) <= abs_tol or (d != 0 and abs(d - s) / abs(d) <= rel_tol):
        return {"status": "match"}
    return {"status": "mismatch", "dax": d, "sql": s, "abs_diff": d - s}


def _band(score):
    for lo, name in [(90, "AUTO"), (70, "AUTO_SPOT_CHECK"), (40, "NEEDS_REVIEW"), (11, "MANUAL_PORT")]:
        if score >= lo:
            return name
    return "UNSUPPORTED"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--slices", default="")
    a = ap.parse_args()
    slices = [s.strip() for s in a.slices.split(",") if s.strip()]
    if a.emit:
        emit(a.workdir, slices)
    if a.compare:
        compare(a.workdir)
    if not (a.emit or a.compare):
        print("choose --emit and/or --compare")


if __name__ == "__main__":
    main()
