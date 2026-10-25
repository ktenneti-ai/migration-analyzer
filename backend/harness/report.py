"""Renders harness results as report.md (for people) and results.json (for
diffing runs), optionally redacted so the report can be shared without
exposing a customer's model."""
from __future__ import annotations

import hashlib
import json
import secrets
from collections import Counter, defaultdict
from datetime import datetime, timezone

from harness.worker import SEVERITIES

MAX_EXAMPLES = 5

_SCORECARD = [
    ("Tables extracted", "tables_matched", "tables_truth"),
    ("Columns extracted", "columns_matched", "columns_truth"),
    ("Measures extracted", "measures_matched", "measures_truth"),
    ("Measure DAX extracted intact", "measure_expr_faithful", "measures_truth"),
    ("Relationships extracted", "relationships_matched", "relationships_truth"),
    ("Relationship flags correct (M2M / bi-di / active)", None, "relationship_props_checked"),
    ("Measure lineage edges captured", "lineage_edges_matched", "lineage_edges_truth"),
    ("Teradata sources captured", "teradata_tables_captured", "teradata_tables_truth"),
    ("Unresolved-reference gaps that are real", "gaps_confirmed", "analyzer_gaps"),
    ('"auto" SQL translations with no issue found', None, "auto_translations"),
    ('"auto_spot_check" translations with no issue found', None, "spot_check_translations"),
]

_FEATURE_LABELS = {
    "calculation_group": "Calculation groups",
    "calculation_item": "Calculation items",
    "role": "Security roles",
    "rls_table_filter": "Row-level security filters",
    "ols_column_permission": "Object-level (column) security",
    "perspective": "Perspectives",
    "translation_culture": "Translation cultures",
    "calculated_table": "Calculated tables",
    "calculated_column": "Calculated columns",
    "field_parameter": "Field parameters",
    "hierarchy": "Hierarchies",
    "kpi": "KPIs",
    "dynamic_format_string": "Dynamic format strings",
    "detail_rows_expression": "Detail-rows expressions",
    "incremental_refresh_policy": "Incremental refresh policies",
    "incremental_refresh_partition": "Incremental refresh partitions",
    "directquery_partition": "DirectQuery partitions",
    "dual_partition": "Dual-mode partitions",
    "direct_lake_or_entity_partition": "Direct Lake / entity partitions",
    "legacy_query_partition": "Legacy query partitions",
    "legacy_data_source": "Legacy data sources",
    "shared_m_expression_or_parameter": "Shared M expressions / parameters",
}


class Redactor:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._salt = secrets.token_hex(16)  # per run, so hashes can't be dictionary-reversed
        self._models: dict[str, str] = {}

    def model(self, path: str) -> str:
        if not self.enabled:
            return path
        return self._models.setdefault(path, f"model-{len(self._models) + 1:03d}")

    def obj(self, s: str) -> str:
        if not self.enabled or not s:
            return s
        return "obj-" + hashlib.sha256((self._salt + s).encode()).hexdigest()[:10]

    def result(self, r: dict) -> dict:
        if not self.enabled:
            return r
        r = json.loads(json.dumps(r, default=str))
        r["input"]["path"] = self.model(r["input"]["path"])
        r["input"]["upload_filename"] = ""
        for f in r.get("findings", []):
            f["object"] = self.obj(f["object"])
            f["evidence"] = ""
        for err in [r.get("error")] + list((r.get("stage_errors") or {}).values()):
            if err:
                err["message"] = "(redacted)"
        return r


def _pct(num: int, den: int) -> str:
    return "n/a" if not den else f"{100 * num / den:.1f}% ({num:,} / {den:,})"


def render(results: list[dict], skipped: list[dict], args_summary: str, redact: bool) -> tuple[str, list[dict]]:
    red = Redactor(redact)
    results = [red.result(r) for r in results]
    skipped = [{**s, "path": red.model(s["path"])} for s in skipped]

    total = Counter()
    for r in results:
        total.update(r.get("metrics") or {})
    statuses = Counter(r["status"] for r in results)

    out: list[str] = []
    w = out.append
    w("# Real-model accuracy harness report\n")
    w(f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} · {args_summary}"
      + (" · **redacted**" if redact else "") + "\n")

    w("## Corpus\n")
    w("| Outcome | Models |\n|---|---:|")
    for status, label in [
        ("ok", "Analyzed end-to-end"),
        ("not_extracted", "Valid model, analyzer didn't recognize the format"),
        ("rejected", "Rejected by the analyzer"),
        ("crashed", "Analyzer crashed during ingestion"),
        ("timeout", "Timed out"),
        ("harness_error", "Harness error (the harness's own bug)"),
        ("not_a_model", "JSON that isn't a semantic model (ignored)"),
    ]:
        if statuses.get(status):
            w(f"| {label} | {statuses[status]} |")
    if skipped:
        w(f"| Skipped (unsupported input, see below) | {len(skipped)} |")
    w("")

    w("## Accuracy scorecard\n")
    w("Ground truth is the harness's own independent parse of each source file. Models the analyzer "
      "crashed on or rejected count as 0 extracted.\n")
    w("| Check | Result |\n|---|---|")
    for label, num_key, den_key in _SCORECARD:
        den = total.get(den_key, 0)
        if num_key is None:
            flagged_key = {
                "relationship_props_checked": "relationship_props_wrong",
                "auto_translations": "auto_translations_flagged",
                "spot_check_translations": "spot_check_translations_flagged",
            }[den_key]
            num = den - total.get(flagged_key, 0)
        else:
            num = total.get(num_key, 0)
        w(f"| {label} | {_pct(num, den)} |")
    w("")

    findings = [(r, f) for r in results for f in r.get("findings", [])]
    by_check: dict[str, list] = defaultdict(list)
    for r, f in findings:
        by_check[f["check"]].append((r, f))

    def sev_rank(check: str) -> tuple:
        sev = min(SEVERITIES.index(f["severity"]) for _, f in by_check[check])
        return sev, -len(by_check[check])

    w("## Findings by check\n")
    if not by_check:
        w("No findings.\n")
    else:
        w("| Severity | Check | Findings | Models | What it means |\n|---|---|---:|---:|---|")
        for check in sorted(by_check, key=sev_rank):
            rows = by_check[check]
            sev = SEVERITIES[sev_rank(check)[0]]
            models = len({r["input"]["path"] for r, _ in rows})
            w(f"| {sev} | `{check}` | {len(rows):,} | {models} | {rows[0][1]['detail']} |")
        w("")

        w("### Examples\n")
        for check in sorted(by_check, key=sev_rank):
            if check == "unresolved_in_source":
                continue
            w(f"#### `{check}`\n")
            for r, f in by_check[check][:MAX_EXAMPLES]:
                line = f"- **{r['input']['path']}** · `{f['object']}`"
                if f["evidence"]:
                    line += f"  \n  {f['evidence']}"
                w(line)
            if len(by_check[check]) > MAX_EXAMPLES:
                w(f"- … and {len(by_check[check]) - MAX_EXAMPLES:,} more in results.json")
            w("")

    feature_totals, feature_models = Counter(), Counter()
    sources, source_models = Counter(), Counter()
    unknown_fn, unknown_fn_models = Counter(), Counter()
    bands = Counter()
    for r in results:
        for k, v in (r.get("features") or {}).items():
            feature_totals[k] += v
            feature_models[k] += 1
        for k, v in (r.get("data_sources") or {}).items():
            sources[k] += v
            source_models[k] += 1
        for k, v in (r.get("unknown_functions") or {}).items():
            unknown_fn[k] += v
            unknown_fn_models[k] += 1
        bands.update(r.get("bands") or {})

    w("## Model features the analyzer doesn't model\n")
    w("Present in the source models but with no place in the analyzer's canonical model, so they are "
      "silently left out of the inventory, gaps, report and migration plan.\n")
    if feature_totals:
        w("| Feature | Count | Models |\n|---|---:|---:|")
        for k, v in feature_totals.most_common():
            w(f"| {_FEATURE_LABELS.get(k, k)} | {v:,} | {feature_models[k]} |")
    else:
        w("None found.")
    w("")

    if sources:
        w("## Data sources (from partition M queries)\n")
        w("| Source | Partitions | Models |\n|---|---:|---:|")
        for k, v in sources.most_common():
            w(f"| {k} | {v:,} | {source_models[k]} |")
        w("")

    if bands:
        w("## Classifier band distribution\n")
        w("| Band | Measures |\n|---|---:|")
        for b in ("AUTO", "AUTO_SPOT_CHECK", "NEEDS_REVIEW", "MANUAL_PORT", "UNSUPPORTED"):
            if bands.get(b):
                w(f"| {b} | {bands[b]:,} |")
        w("")

    if unknown_fn:
        w("## DAX functions the classifier has no rule for\n")
        w("Each one costs a measure 30 points and pushes it toward MANUAL_PORT. Commonly used ones are "
          "candidates to catalog in `app/parsers/dax/classifier.py`.\n")
        w("| Function | Uses | Models |\n|---|---:|---:|")
        for k, v in unknown_fn.most_common(30):
            w(f"| `{k}` | {v:,} | {unknown_fn_models[k]} |")
        w("")

    w("## Per model\n")
    w("| Model | Format | Status | Size | Time (s) | Tables | Measures | DAX intact | Rels | "
      "Critical/High | Medium |\n|---|---|---|---:|---:|---|---|---|---|---:|---:|")
    for r in sorted(results, key=lambda r: r["input"]["path"]):
        if r["status"] == "not_a_model":
            continue
        m = r.get("metrics") or {}
        sev = Counter(f["severity"] for f in r.get("findings", []))
        size = r["input"].get("bytes")
        t = sum((r.get("timings") or {}).values())
        w(f"| {r['input']['path']} | {r['input'].get('format', r['input']['kind'])} | {r['status']} | "
          f"{f'{size / 1024:,.0f} KB' if size else ''} | {t:.1f} | "
          f"{m.get('tables_matched', 0)}/{m.get('tables_truth', 0)} | "
          f"{m.get('measures_matched', 0)}/{m.get('measures_truth', 0)} | "
          f"{m.get('measure_expr_faithful', 0)}/{m.get('measures_truth', 0)} | "
          f"{m.get('relationships_matched', 0)}/{m.get('relationships_truth', 0)} | "
          f"{sev['critical'] + sev['high']} | {sev['medium']} |")
    w("")

    notes = sorted({n for r in results for n in r["input"].get("notes", [])})
    if notes:
        w("Input handling notes:\n")
        for n in notes:
            w(f"- {n}")
        w("")

    errors = [(r, name, e) for r in results
              for name, e in ([("ingest", r["error"])] if r.get("error") else [])
              + list((r.get("stage_errors") or {}).items())]
    if errors:
        w("## Errors\n")
        for r, name, e in errors:
            w(f"<details><summary><b>{r['input']['path']}</b> · {name} · {e['type']}</summary>\n")
            w(f"```\n{e['message']}\n\n{e['traceback']}\n```\n</details>\n")

    if skipped:
        w("## Skipped inputs\n")
        for s in skipped:
            w(f"- {s['path']}: {s['reason']}")
        w("")

    return "\n".join(out), results
