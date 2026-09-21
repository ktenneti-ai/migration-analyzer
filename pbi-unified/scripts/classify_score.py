#!/usr/bin/env python3
"""Stage 3 — Classification + confidence scoring (see references/confidence-scoring.md).

Reads model.json + inventory.json, writes classification.json:
  per measure: score (0-100), band, tier, category (A-F), reasons[], parity: "untested"
  plus model_score and model_penalties.

The A-F category is a human-readable label derived from score + pattern:
  A = simple aggregation (90-100, no complex patterns)
  B = derived measure (70-89, references other measures or has pattern rewrites)
  C = time intelligence (any score, uses time intel functions)
  D = filtered aggregate (any score, CALCULATE with filter args)
  E = semi-additive (any score, uses semi-additive functions)
  F = complex/untranslatable (<40 or RLS/calc groups/EARLIER)

Usage: python classify_score.py --workdir conversion/sales [--usage usage.json]
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _shared import load_json, save_json

DIRECT = {"SUM","AVERAGE","MIN","MAX","COUNTROWS","COUNT","COUNTA","DISTINCTCOUNT",
          "DISTINCTCOUNTNOBLANK","DIVIDE","BLANK","ABS","ROUND","INT","MOD","SQRT","EXP",
          "LN","LOG","POWER","CONCATENATE","LEFT","RIGHT","MID","LEN","UPPER","LOWER",
          "TRIM","SUBSTITUTE","SEARCH","FIND","YEAR","MONTH","DAY","HOUR","MINUTE",
          "WEEKDAY","EOMONTH","TODAY","NOW","FORMAT","TRUE","FALSE","AND","OR","NOT"}
TIER2 = {"IF","SWITCH","ISBLANK","COALESCE","SELECTEDVALUE","COUNTBLANK",
         "SUMX","AVERAGEX","MINX","MAXX","COUNTX","VALUES","HASONEVALUE","CALCULATE"}
TIME_INTEL = {"SAMEPERIODLASTYEAR","DATESYTD","DATESQTD","DATESMTD","DATEADD",
              "PARALLELPERIOD","TOTALYTD","TOTALQTD","TOTALMTD","DATESINPERIOD",
              "DATESBETWEEN","PREVIOUSMONTH","PREVIOUSQUARTER","PREVIOUSYEAR","PREVIOUSDAY",
              "NEXTMONTH","NEXTQUARTER","NEXTYEAR","NEXTDAY","FIRSTDATE","LASTDATE",
              "STARTOFMONTH","STARTOFQUARTER","STARTOFYEAR","ENDOFMONTH","ENDOFQUARTER","ENDOFYEAR"}
SEMI_ADDITIVE = {"LASTNONBLANK","LASTNONBLANKVALUE","FIRSTNONBLANK","FIRSTNONBLANKVALUE",
                 "OPENINGBALANCEMONTH","OPENINGBALANCEQUARTER","OPENINGBALANCEYEAR",
                 "CLOSINGBALANCEMONTH","CLOSINGBALANCEQUARTER","CLOSINGBALANCEYEAR"}
REL_MOD = {"USERELATIONSHIP"}; VIRTUAL_REL = {"TREATAS","CROSSFILTER"}
RLS_FUNCS = {"USERNAME","USERPRINCIPALNAME","CUSTOMDATA"}
RANKY = {"RANKX","TOPN"}
EARLIER = {"EARLIER","EARLIEST"}
KNOWN = (DIRECT | TIER2 | TIME_INTEL | SEMI_ADDITIVE | REL_MOD | VIRTUAL_REL | RLS_FUNCS
         | RANKY | EARLIER | {"ALL","ALLEXCEPT","ALLSELECTED","REMOVEFILTERS","KEEPFILTERS",
         "FILTER","RELATED","RELATEDTABLE","LOOKUPVALUE","VAR","RETURN","ADDCOLUMNS",
         "SUMMARIZE","SUMMARIZECOLUMNS","CROSSJOIN","GENERATE","DISTINCT","CONCATENATEX",
         "ISFILTERED","ISCROSSFILTERED","SELECTEDMEASURE","IN","MAXX","MINX"})

BANDS = [(90,"AUTO"),(70,"AUTO_SPOT_CHECK"),(40,"NEEDS_REVIEW"),(11,"MANUAL_PORT"),(0,"UNSUPPORTED")]


def band(score):
    for lo, name in BANDS:
        if score >= lo:
            return name
    return "UNSUPPORTED"


def classify_category(funcs, info, score):
    """Derive the A-F human-readable category from function patterns."""
    if funcs & RLS_FUNCS or funcs & EARLIER or score < 11:
        return "F"
    if funcs & SEMI_ADDITIVE:
        return "E"
    if funcs & TIME_INTEL:
        return "C"
    if info.get("calculate_filter_kinds"):
        return "D"
    if info.get("measure_refs") or (funcs & TIER2):
        return "B"
    return "A"


def score_one(name, info, bidi_tables, m2m_tables):
    funcs, reasons, score, caps = set(info["functions"]), [], 100, []
    def ded(v, why):
        nonlocal score
        score -= v
        reasons.append(f"-{v}: {why}")
    def cap(v, why):
        caps.append((v, why))

    if funcs & RLS_FUNCS:
        cap(10, f"RLS-coupled function {sorted(funcs & RLS_FUNCS)} — UNSUPPORTED in view")
    if funcs & VIRTUAL_REL:
        cap(25, f"virtual relationship {sorted(funcs & VIRTUAL_REL)}")
    if funcs & REL_MOD:
        cap(30, "USERELATIONSHIP rewires join graph per-measure")
    if funcs & EARLIER:
        cap(25, "nested row context (EARLIER)")
    if funcs & TIME_INTEL:
        cap(35, f"time intelligence {sorted(funcs & TIME_INTEL)[:3]}")
    if funcs & SEMI_ADDITIVE:
        cap(35, "semi-additive — needs snapshot/window pattern")
    if "all_family" in info["calculate_filter_kinds"] or funcs & {"ALL","ALLEXCEPT","REMOVEFILTERS","ALLSELECTED"}:
        cap(55, "ALL-family: total/window semantics not a plain aggregate")
    if set(info["tables"]) & bidi_tables:
        cap(45, "touches bi-directional relationship path")
    if set(info["tables"]) & m2m_tables:
        cap(45, "touches many-to-many relationship path")

    t2 = funcs & (TIER2 - {"CALCULATE"})
    if t2:
        ded(min(12 * len(t2), 36), f"pattern rewrites {sorted(t2)[:4]}")
    if "boolean" in info["calculate_filter_kinds"]:
        ded(15, "CALCULATE boolean filter -> FILTER clause")
    if "filter_table" in info["calculate_filter_kinds"]:
        ded(25, "CALCULATE with FILTER() table arg")
    if "keepfilters" in info["calculate_filter_kinds"]:
        ded(20, "KEEPFILTERS semantics")
    if "other" in info["calculate_filter_kinds"]:
        ded(20, "CALCULATE with unrecognized filter arg")
    if info["uses_var"]:
        ded(10, "VAR/RETURN needs inlining/decomposition")
    if info["iterator_over_virtual_table"]:
        ded(35, "iterator over virtual table -> CTE/pre-agg")
    if funcs & RANKY:
        ded(30, "RANKX/TOPN -> window logic, likely consumer-side")
    if "LOOKUPVALUE" in funcs:
        ded(25, "LOOKUPVALUE -> new explicit join")
    if info.get("blank_zero_sensitive"):
        ded(10, "BLANK vs 0/NULL sensitive comparison")
    unknown = funcs - KNOWN
    if unknown:
        ded(min(30 * len(unknown), 60), f"uncataloged functions {sorted(unknown)[:4]}")

    score = max(score, 0)
    for v, why in caps:
        if score > v:
            score = v
            reasons.append(f"cap {v}: {why}")
    tier = ("T1" if score >= 90 else "T2" if score >= 70 else
            "T3" if score >= 40 else "T4")
    category = classify_category(funcs, info, score)
    return score, tier, category, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--usage")
    a = ap.parse_args()
    model = load_json(os.path.join(a.workdir, "model.json"), "model.json")
    inv = load_json(os.path.join(a.workdir, "inventory.json"), "inventory.json")
    feats = model["features"]
    bidi = {r["from_table"] for r in feats["bidirectional_relationships"]} | \
           {r["to_table"] for r in feats["bidirectional_relationships"]}
    m2m = {r["from_table"] for r in feats["m2m_relationships"]} | \
          {r["to_table"] for r in feats["m2m_relationships"]}
    results = {}
    for name in inv["topological_order"]:
        info = inv["measures"][name]
        score, tier, category, reasons = score_one(name, info, bidi, m2m)
        dep_scores = [results[d]["score"] for d in info["measure_refs"] if d in results]
        if dep_scores and min(dep_scores) < score:
            score = min(dep_scores)
            reasons.append(f"propagated from weakest dependency (score {score})")
        results[name] = {"score": score, "band": band(score), "tier": tier,
                         "category": category, "reasons": reasons, "parity": "untested",
                         "deps": info["measure_refs"]}
    for cyc in inv["cycles"]:
        for n in cyc:
            if n in results:
                results[n].update(score=20, band="MANUAL_PORT",
                                  reasons=results[n]["reasons"] + ["dependency cycle"])
    weights = load_json(a.usage, "usage.json") if a.usage else {}
    tot_w = sum(weights.get(n, 1) for n in results) or 1
    model_score = sum(r["score"] * weights.get(n, 1) for n, r in results.items()) / tot_w
    penalties = []
    if feats["calculation_groups"]:
        model_score -= 25
        penalties.append("-25: calculation groups present (matrix not signed off)")
    high_open = sum(bool(feats[k]) for k in ("bidirectional_relationships", "m2m_relationships"))
    if feats["roles_rls"]:
        model_score -= 5
        penalties.append("-5: RLS roles present")
    if high_open:
        d = min(10 * high_open, 30)
        model_score -= d
        penalties.append(f"-{d}: open HIGH model-coverage items")
    if feats.get("inactive_relationships"):
        model_score -= 3
        penalties.append("-3: inactive relationships present (USERELATIONSHIP may be in use)")
    if feats.get("calculated_tables"):
        model_score -= 3
        penalties.append("-3: calculated tables present (need materialization)")
    out = {"measures": results,
           "model_score": round(max(model_score, 0), 1),
           "model_penalties": penalties,
           "band_counts": {b: sum(1 for r in results.values() if r["band"] == b)
                           for _, b in BANDS},
           "category_counts": {cat: sum(1 for r in results.values() if r["category"] == cat)
                               for cat in "ABCDEF"}}
    save_json(out, os.path.join(a.workdir, "classification.json"))
    print(f"classification.json: model_score={out['model_score']} bands={out['band_counts']}")
    print(f"  categories: {out['category_counts']}")


if __name__ == "__main__":
    main()
