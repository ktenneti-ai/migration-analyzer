#!/usr/bin/env python3
"""Stage 8 — conversion_report.md (human) + conversion_manifest.json (reviewer contract).

The manifest is the single artifact the reviewer step (Step 7) consumes.

Usage: python report.py --workdir conversion/sales [--docs-checked YYYY-MM-DD]
"""
import argparse, datetime, glob, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _shared import load_json, save_json, save_text

import json


def _count_yaml_measures(wd):
    """Count measures across all metric_view*.yaml files in the workdir."""
    import re
    total = 0
    files = sorted(glob.glob(os.path.join(wd, "metric_view*.yaml")))
    for fp in files:
        in_measures = False
        with open(fp, encoding="utf-8") as f:
            for line in f:
                stripped = line.rstrip()
                if stripped == "measures:":
                    in_measures = True
                    continue
                if in_measures and re.match(r"^- name:", stripped):
                    total += 1
                elif in_measures and not stripped.startswith(" ") and not stripped.startswith("-") and stripped:
                    in_measures = False
    return total, len(files)


def _count_wrapper_measures(wd):
    """Count wrapper measures (window-function columns) from wrapper_view*.sql files."""
    import re
    total = 0
    files = sorted(glob.glob(os.path.join(wd, "wrapper_view*.sql")))
    col_re = re.compile(r"AS `[^`]+`\s*[,;]?\s*$")
    base_re = re.compile(r"^\s*MEASURE\(`[^`]+`\)\s+AS\s+`")
    for fp in files:
        with open(fp, encoding="utf-8") as f:
            for line in f:
                if col_re.search(line) and not base_re.match(line):
                    total += 1
    return total, len(files)


def _detect_fact_groups(wd, tr):
    """Collect unique fact groups from translations.json."""
    groups = {}
    for name, m in tr.get("measures", {}).items():
        fg = m.get("fact_group")
        if fg:
            groups.setdefault(fg, []).append(name)
    return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--docs-checked", default=None,
                    help="date Metric View syntax was verified vs Databricks docs")
    a = ap.parse_args()
    wd = a.workdir
    model = load_json(os.path.join(wd, "model.json"), "model.json")
    cls = load_json(os.path.join(wd, "classification.json"), "classification.json")
    tr = load_json(os.path.join(wd, "translations.json"), "translations.json")
    parity_path = os.path.join(wd, "parity_results.json")
    parity = load_json(parity_path, "parity_results.json") if os.path.exists(parity_path) else {}
    profile_path = os.path.join(wd, "profile.json")
    profile = load_json(profile_path, "profile.json") if os.path.exists(profile_path) else None
    feats = model["features"]
    ms = cls["measures"]

    model_measure_names = {m["name"] for t in model["tables"] for m in t["measures"]}
    cls_names = set(ms)
    tr_names = set(tr["measures"])
    dropped_from_cls = sorted(model_measure_names - cls_names)
    dropped_from_tr = sorted(model_measure_names - tr_names)
    extra_in_cls = sorted(cls_names - model_measure_names)

    yaml_measure_count, yaml_file_count = _count_yaml_measures(wd)
    wrapper_measure_count, wrapper_file_count = _count_wrapper_measures(wd)
    fact_groups = _detect_fact_groups(wd, tr)

    tr_statuses = {}
    for m in tr["measures"].values():
        s = m.get("status", "unknown")
        tr_statuses[s] = tr_statuses.get(s, 0) + 1

    manifest = {
        "skill": "pbi-unified",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "model_name": model["name"],
        "docs_syntax_checked": a.docs_checked,
        "model_score": cls["model_score"],
        "model_penalties": cls["model_penalties"],
        "band_counts": cls["band_counts"],
        "category_counts": cls.get("category_counts", {}),
        "fact_groups": list(fact_groups.keys()),
        "yaml_measures_emitted": yaml_measure_count,
        "wrapper_measures_emitted": wrapper_measure_count,
        "measures": {n: {**ms[n], "status": tr["measures"][n]["status"],
                         "sql": tr["measures"][n]["sql"],
                         "original_dax": tr["measures"][n]["original_dax"],
                         "fact_group": tr["measures"][n].get("fact_group")}
                     for n in ms if n in tr["measures"]},
        "features": feats,
        "revisions": tr.get("revisions", []),
        "artifacts": {k: os.path.join(wd, v) for k, v in {
            "spec": "metric_view.yaml", "ddl": "create_view.sql",
            "parity": "parity_results.json", "queries": "parity_queries"}.items()},
    }
    save_json(manifest, os.path.join(wd, "conversion_manifest.json"))

    lines = [f"# Conversion Report — {model['name']}",
             f"_Generated {manifest['generated_at']} · pbi-unified · revision {len(manifest['revisions'])}_",
             "",
             f"**Model conversion score: {cls['model_score']}/100**",
             f"Bands: " + " · ".join(f"{b}: {c}" for b, c in cls["band_counts"].items() if c),
             ""]
    if cls.get("category_counts"):
        lines.append(f"Categories: " + " · ".join(
            f"{cat}: {cnt}" for cat, cnt in sorted(cls["category_counts"].items()) if cnt))
        lines.append("")
    if a.docs_checked:
        lines.append(f"Metric View syntax verified against Databricks docs on **{a.docs_checked}**.")
    else:
        lines.append("⚠️ Metric View syntax **not yet verified** against current Databricks docs — do before execution.")
    if cls["model_penalties"]:
        lines += ["", "**Model penalties:** " + "; ".join(cls["model_penalties"])]

    lines += ["", "## Coverage check (exhaustive enumeration)",
              f"model.json: {len(model_measure_names)} measures extracted · "
              f"classification.json: {len(cls_names)} · translations.json: {len(tr_names)}"]
    if not (dropped_from_cls or dropped_from_tr or extra_in_cls):
        lines.append("✅ Every extracted measure is present at every stage. No silent drops.")
    else:
        if dropped_from_cls:
            lines.append(f"❌ **{len(dropped_from_cls)} measure(s) missing from classification.json** "
                         f"(re-run classify_score.py): {dropped_from_cls}")
        if dropped_from_tr:
            lines.append(f"❌ **{len(dropped_from_tr)} measure(s) missing from translations.json** "
                         f"(re-run translate.py): {dropped_from_tr}")
        if extra_in_cls:
            lines.append(f"⚠️ {len(extra_in_cls)} name(s) in classification.json not found in "
                         f"model.json — stale artifact from a prior model version? {extra_in_cls}")

    lines += ["", "## Build output summary"]
    if len(fact_groups) > 1:
        lines.append(f"**Multi-fact model**: {len(fact_groups)} fact groups detected.")
        for fg_name, fg_measures in sorted(fact_groups.items()):
            lines.append(f"- **{fg_name}**: {len(fg_measures)} measures")
    elif len(fact_groups) == 1:
        fg_name = list(fact_groups.keys())[0]
        lines.append(f"**Single-fact model**: source table = {fg_name}")
    else:
        lines.append("⚠️ No fact groups detected in translations.json")

    lines.append("")
    lines.append(f"| Output | Files | Measures |")
    lines.append(f"|--------|-------|----------|")
    lines.append(f"| Metric View YAML | {yaml_file_count} | {yaml_measure_count} |")
    lines.append(f"| Wrapper View SQL | {wrapper_file_count} | {wrapper_measure_count} |")
    lines.append(f"| **Total KPI coverage** | | **{yaml_measure_count + wrapper_measure_count}/{len(model_measure_names)}** |")
    lines.append("")

    excluded_count = len(model_measure_names) - yaml_measure_count - wrapper_measure_count
    if excluded_count > 0:
        lines.append(f"**{excluded_count} measure(s) require manual review** — see Manual Review Required sheet in conversion_details.xlsx.")
    else:
        lines.append("✅ All measures covered by metric view or wrapper view.")

    lines.append("")
    lines.append(f"Translation statuses: " + " · ".join(f"{s}: {c}" for s, c in sorted(tr_statuses.items()) if c))

    lines += ["", "## Source table profiling"]
    if profile:
        p_tables = profile["tables"]
        matched = sum(1 for e in p_tables.values() if e.get("physical_table"))
        lines.append(f"{matched}/{len(p_tables)} PBI tables matched to a Unity Catalog table "
                     f"(profile_tables.py, {'catalog scan verified' if profile.get('catalog_scan_provided') else 'NAME-ONLY, unverified'}).")
        n_flags = sum(len(e.get("column_reconciliation", {}).get("dtype_flags", []))
                     for e in p_tables.values())
        n_missing_cols = sum(len(e.get("column_reconciliation", {}).get("missing_in_catalog", []))
                            for e in p_tables.values())
        n_missing_tables = sum(1 for e in p_tables.values() if not e.get("physical_table"))
        if n_missing_tables:
            lines.append(f"❌ {n_missing_tables} table(s) have no Unity Catalog match — see missing_tables.sql "
                         "(BLOCKER: cannot join/aggregate until resolved).")
        if n_missing_cols:
            lines.append(f"⚠️ {n_missing_cols} PBI column(s) not found in their matched Unity Catalog table "
                         "— see gap_report.md.")
        if n_flags:
            lines.append(f"⚠️ {n_flags} column(s) flagged for a data-type mismatch (VARCHAR-numeric / "
                         "string-date) requiring an explicit cast before aggregation — see gap_report.md.")
        if not (n_missing_tables or n_missing_cols or n_flags):
            lines.append("✅ No table/column gaps or type flags outstanding.")
    else:
        lines.append("⚠️ Not yet run — `profile_tables.py` produces `profile.json`/`gap_report.md`/"
                     "`table_map.json` and should complete before `build_view.py`.")

    lines += ["", "## Manual checklist (do these, in order)"]
    n = 0
    for name, m in sorted(ms.items(), key=lambda kv: kv[1]["score"]):
        if m["band"] in ("NEEDS_REVIEW", "MANUAL_PORT", "UNSUPPORTED") or m["parity"] == "MISMATCH":
            n += 1
            fg_label = ""
            tr_m = tr["measures"].get(name, {})
            if tr_m.get("fact_group") and len(fact_groups) > 1:
                fg_label = f" [{tr_m['fact_group']}]"
            lines.append(f"{n}. **{name}**{fg_label} [{m['band']}, {m['score']}, Cat {m.get('category','?')}] — " +
                         "; ".join(m["reasons"][-3:]))
    for key, label, sev in [("calculation_groups", "Calculation groups: decide item×measure matrix", "BLOCKER"),
                            ("bidirectional_relationships", "Bi-directional relationships: redesign filter paths", "HIGH"),
                            ("m2m_relationships", "Many-to-many relationships: bridge-table design", "HIGH"),
                            ("roles_rls", "RLS roles: deliver UC row filters separately", "HIGH"),
                            ("calculated_tables", "Calculated tables: materialize as Delta (CTAS)", "MEDIUM"),
                            ("inactive_relationships", "Inactive relationships: add role-played join aliases if USERELATIONSHIP used", "MEDIUM")]:
        if feats.get(key):
            n += 1
            lines.append(f"{n}. [{sev}] {label} ({len(feats[key])})")
    if n == 0:
        lines.append("None — all measures AUTO/SPOT and no open model features.")

    if parity:
        match = sum(1 for r in parity.values() if r.get("status") == "match")
        lines += ["", "## Parity", f"{match}/{len(parity)} measure×slice pairs match."]
        for k, r in parity.items():
            if r.get("status") == "mismatch":
                lines.append(f"- ❌ {k}: {json.dumps(r)[:200]}")
    else:
        lines += ["", "## Parity", "Not yet run — `reconcile.py --emit` produced the query pack."]

    lines += ["", "## Per-measure detail",
              "| Measure | Score | Band | Cat | Fact Group | Status | Parity | Top reason |",
              "|---|---|---|---|---|---|---|---|"]
    for name, m in sorted(ms.items(), key=lambda kv: kv[1]["score"]):
        top = m["reasons"][0] if m["reasons"] else "clean mechanical translation"
        tr_m = tr["measures"].get(name, {})
        fg = tr_m.get("fact_group", "—")
        status = tr_m.get("status", "—")
        lines.append(f"| {name} | {m['score']} | {m['band']} | {m.get('category','?')} | {fg} | {status} | {m['parity']} | {top} |")

    lines += ["", "## Optimization recommendations",
              "See references/optimization-guide.md — populate [emit-now] items that fired:",
              "- Pre-aggregation candidates: measures flagged 'iterator over virtual table' / semi-additive",
              "- dim_date with period columns if any time-intelligence measures exist (Cat C)",
              "- Liquid clustering on fact date key + top filter dimension",
              "- Grain checks in parity_queries/grain_checks.sql must return 0 rows",
              "- Wide dimension tables: consider column pruning or split into separate dim views",
              "- Duplicate subexpressions across measures: extract as a shared measure"]

    lines += ["", "## Testing patterns (run in order)",
              "1. **Smoke test**: CREATE VIEW succeeds; SELECT * LIMIT 10 returns rows",
              "2. **Granularity test**: every dimension-side join key is unique (grain_checks.sql)",
              "3. **Window isolation**: measures with window semantics return expected results per-slice",
              "4. **NULL/empty test**: measures handle BLANK/NULL correctly (filter on NULL rows)",
              "5. **Cross-validation**: DAX vs SQL parity for top-usage measures (reconcile.py)"]

    lines += ["", "## Genie / AI grounding readiness",
              "- Every measure's PBI description/displayFolder/formatString carried into conversion_details.xlsx",
              "- Business synonyms documented for ambiguous names",
              "- Time-pattern phrasing mapped to period-shifted measures (wrapper views)",
              "- Edge cases (BLANK/NULL, currency rounding) noted in conversion_details.xlsx"]
    save_text("\n".join(lines), os.path.join(wd, "conversion_report.md"))
    print(f"conversion_report.md + conversion_manifest.json written "
          f"(model_score={cls['model_score']}, yaml={yaml_measure_count}, "
          f"wrapper={wrapper_measure_count}, manual={n})")


if __name__ == "__main__":
    main()
