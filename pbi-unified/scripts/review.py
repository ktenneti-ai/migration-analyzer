#!/usr/bin/env python3
"""Stage 7.2 — Automated review (rubric A/B/C/D mechanical checks).

Reads conversion_manifest.json (+ metric_view.yaml next to it), writes
review_findings.json. The reviewing assistant ADDS its own findings (C1
re-derivation, C2 parity triage, judgment calls) to the same file before
making the change request.

Enhanced checks beyond the original:
  - B5: dropped CALCULATE filters (parse DAX provenance, verify SQL has WHERE)
  - B10: unresolved measure references in spec
  - A2: relationship coverage (model.json relationships vs spec joins)

Usage: python review.py --manifest conversion/sales/conversion_manifest.json
"""
import argparse, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from _shared import snake, load_json, save_json

SEV_W = {"CRITICAL": 25, "HIGH": 10, "MEDIUM": 4, "LOW": 1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    a = ap.parse_args()
    man = load_json(a.manifest, "conversion_manifest.json")
    wd = os.path.dirname(a.manifest)
    findings = []
    F = lambda check, sev, obj, msg, fix=None: findings.append(
        {"finding": check, "severity": sev, "object": obj, "message": msg,
         **({"proposed_fix": fix} if fix else {})})

    spec_path = os.path.join(wd, "metric_view.yaml")
    spec_text = ""
    if os.path.exists(spec_path):
        with open(spec_path, encoding="utf-8") as f:
            spec_text = f.read()
    spec = None
    if spec_text:
        try:
            import yaml
            spec = yaml.safe_load(spec_text)
        except Exception as e:
            F("A1", "CRITICAL", "spec", f"YAML does not parse: {e}")
    else:
        F("A1", "CRITICAL", "spec", "metric_view.yaml missing")

    profile_path = os.path.join(wd, "profile.json")
    varchar_numeric_cols = set()
    if not os.path.exists(profile_path):
        F("A9", "CRITICAL", "profile", "profile.json missing — table_map.json physical "
          "names/types were never verified against Unity Catalog (gate G8)")
    else:
        profile = load_json(profile_path, "profile.json")
        for tname, entry in profile.get("tables", {}).items():
            if not entry.get("physical_table"):
                F("A9", "CRITICAL", tname, "PBI table has no Unity Catalog match "
                  "(BLOCKER in gap_report.md) — cannot be safely joined/aggregated")
            for flag in entry.get("column_reconciliation", {}).get("dtype_flags", []):
                if flag["issue"] == "varchar_numeric":
                    varchar_numeric_cols.add(snake(flag["column"]))
        if not profile.get("catalog_scan_provided"):
            F("A9", "HIGH", "profile", "profile.json exists but no --catalog-scan was "
              "provided — table matches are unverified name-guesses")

    if spec:
        for k in ("version", "source", "measures"):
            if k not in spec:
                F("A1", "CRITICAL", "spec", f"required key missing: {k}")
        if spec.get("version") not in ("1.1",):
            F("A1", "HIGH", "spec", f"YAML version is '{spec.get('version')}' — expected 1.1")
        joins = spec.get("joins", []) or []

        # A2: relationship coverage
        model_path = os.path.join(wd, "model.json")
        if os.path.exists(model_path):
            model = load_json(model_path, "model.json")
            active_rels = [r for r in model.get("relationships", []) if r.get("is_active", True)]
            join_sources = {j.get("source", "") for j in joins}
            tm_path = os.path.join(wd, "table_map.json")
            if os.path.exists(tm_path):
                tm = load_json(tm_path, "table_map.json")
                for r in active_rels:
                    dim_phys = tm.get("physical", {}).get(r["to_table"])
                    if dim_phys and dim_phys not in join_sources:
                        F("A2", "MEDIUM", r["to_table"],
                          f"active relationship to '{r['to_table']}' ({dim_phys}) "
                          "not represented in spec joins — confirm intentional omission")

        # A4: casts in join predicates
        for j in joins:
            if re.search(r"\b(cast|to_date|trim|upper|lower|substr)\s*\(", j.get("on", ""), re.I):
                F("A4", "HIGH", f"join:{j.get('name')}",
                  "function/cast in join predicate — fix key types upstream (opt D1)")
        # A6: duplicates
        for kind in ("dimensions", "measures"):
            names = [x.get("name") for x in spec.get(kind, []) or []]
            for dup in {n for n in names if names.count(n) > 1}:
                F("A6", "MEDIUM", f"{kind}:{dup}", "duplicate name")

        spec_measures = {m.get("name"): m.get("expr", "") for m in spec.get("measures", []) or []}
        all_measure_names = set(spec_measures.keys())
        for name, expr in spec_measures.items():
            e = expr or ""
            if "-- DAX:" not in e:
                F("B1", "HIGH", name, "missing -- DAX: provenance comment")
            if re.search(r"\bOVER\s*\(", e, re.I):
                F("B2", "CRITICAL", name, "window function inside measure expr (gate G7)",
                  "move to consumer query / companion measure pair")
            if re.search(r"\bSELECT\b", e, re.I):
                F("B2", "CRITICAL", name, "subquery inside measure expr")
            for marker in ("-- REVIEW", "-- CANDIDATE", "-- TODO"):
                if marker in e:
                    F("B9", "CRITICAL", name, f"unreviewed marker '{marker}' shipped in spec")
            body = re.sub(r"--[^\n]*", "", e)
            if re.search(r"(?<![*/+-])\s/\s", body) and "try_divide" not in body:
                F("B3", "HIGH", name, "bare division without try_divide/guard")
            for col in varchar_numeric_cols:
                if re.search(rf"\b{re.escape(col)}\b", body) and \
                   not re.search(rf"try_cast\s*\([^)]*\b{re.escape(col)}\b", body, re.I):
                    F("B11", "CRITICAL", name,
                      f"references '{col}' (flagged varchar_numeric in profile.json) "
                      "without an apparent try_cast — verify before trusting this sum/avg")

            # B5: dropped CALCULATE filters
            dax_comment = re.search(r"-- DAX:\s*(.*)", e)
            if dax_comment:
                dax_text = dax_comment.group(1)
                if re.search(r"\bCALCULATE\s*\(", dax_text, re.I):
                    if not re.search(r"\bFILTER\s*\(|WHERE\b", body, re.I):
                        F("B5", "HIGH", name,
                          "DAX uses CALCULATE but translated SQL has no FILTER/WHERE — "
                          "verify filter args were intentionally dropped or are ALL-family")

            # B10: unresolved measure references
            for ref_match in re.finditer(r"\[([^\]]+)\]", body):
                ref_name = ref_match.group(1)
                if ref_name in all_measure_names and ref_name != name:
                    F("B10", "HIGH", name,
                      f"unresolved measure reference [{ref_name}] in spec — "
                      "inline the dependency or use MEASURE() in consumer query")

    # C-level from manifest
    for name, m in man.get("measures", {}).items():
        if spec and name in (spec.get("measures") and {x["name"] for x in spec["measures"]} or set()):
            if m.get("band") in ("MANUAL_PORT", "UNSUPPORTED"):
                F("G3", "CRITICAL", name, f"{m['band']} measure included in emitted spec",
                  "drop from spec or complete manual port")
        if m.get("parity") == "MISMATCH":
            F("C2", "CRITICAL", name, "parity mismatch — triage root cause "
              "(fanout / blank semantics / dropped filter / date grain / type)")
    if not man.get("docs_syntax_checked"):
        F("A8", "HIGH", "manifest", "Metric View syntax not verified vs current Databricks docs (gate G6)")
    feats = man.get("features", {})
    for k, msg in (("calculation_groups", "calculation groups undecided"),
                   ("bidirectional_relationships", "bi-directional relationships open"),
                   ("m2m_relationships", "many-to-many relationships open"),
                   ("roles_rls", "RLS roles — UC row-filter deliverable")):
        if feats.get(k):
            F("C4", "HIGH", k, msg + " (gate G5) — needs recorded decision")
    grain = os.path.join(wd, "parity_queries", "grain_checks.sql")
    F("A5", "HIGH" if os.path.exists(grain) else "CRITICAL", "joins",
      "run grain_checks.sql — every fanout check must return 0 rows"
      if os.path.exists(grain) else "grain checks not generated (reconcile.py --emit)")

    score = max(0, 100 - sum(SEV_W[f["severity"]] for f in findings))
    crit = any(f["severity"] == "CRITICAL" for f in findings)
    verdict = ("APPROVE" if score >= 90 and not crit else
               "APPROVE_WITH_CONDITIONS" if score >= 70 and not crit else "REJECT")
    out = {"review_score": score, "verdict_hint": verdict,
           "note": "assistant must add C1 re-derivation findings + C2 triage before finalizing",
           "findings": findings}
    save_json(out, os.path.join(wd, "review_findings.json"))
    by_sev = {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
    print(f"review_findings.json: score={score} verdict_hint={verdict} {by_sev}")


if __name__ == "__main__":
    main()
