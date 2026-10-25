"""Analyzes one input: builds ground truth, runs it through the analyzer's
real ingestion path and every downstream generator, and compares.

`analyze()` uses whatever database `app.db.session` is configured with;
`child_main()` is the subprocess entry point and points it at a throwaway
SQLite file first, so a run never touches the app's real database.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import traceback
from collections import Counter
from pathlib import Path

from harness.dax_refs import Ref, Resolver, parse_analyzer_gap, scan
from harness.discover import InputItem, load_text
from harness.truth import TruthModel, extract_from_json_text, extract_from_tmdl_text

SEVERITIES = ("critical", "high", "medium", "low", "info")
EXAMPLE_DAX_CHARS = 240


class _Findings:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, check: str, severity: str, obj: str, detail: str, evidence: str = "") -> None:
        # `detail` must never contain model content (names, DAX) — it's kept
        # under --redact. Anything model-specific goes in `obj` / `evidence`.
        self.items.append(
            {"check": check, "severity": severity, "object": obj, "detail": detail, "evidence": evidence[:600]}
        )


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _clip(s: str) -> str:
    s = _norm(s)
    return s if len(s) <= EXAMPLE_DAX_CHARS else s[:EXAMPLE_DAX_CHARS] + " …"


_REPO_PREFIX = str(Path(__file__).resolve().parents[2]) + os.sep


def _error(exc: BaseException) -> dict:
    tb = "".join(traceback.format_tb(exc.__traceback__)).replace(_REPO_PREFIX, "")
    return {"type": type(exc).__name__, "message": str(exc)[:2000], "traceback": tb[-6000:]}


def build_truth(item: InputItem, text: str) -> TruthModel | None:
    if item.kind in ("pbip_tmdl_folder", "tmdl"):
        return extract_from_tmdl_text(text)
    truth = extract_from_json_text(text)
    if truth is None and item.kind == "json":
        # A .json file holding TMDL is a real-world mistake the app's
        # detector explicitly handles; mirror that.
        if re.match(r"^\s*(createOrReplace|model|table|relationship)\b", text):
            return extract_from_tmdl_text(text)
    return truth


def analyze(root: Path, item: InputItem) -> dict:
    result: dict = {
        "input": {"path": item.path, "kind": item.kind, "upload_filename": item.upload_filename,
                  "notes": list(item.notes)},
        "status": "ok",
        "timings": {},
        "metrics": Counter(),
        "features": {},
        "data_sources": {},
        "bands": {},
        "translation_statuses": {},
        "unknown_functions": {},
        "findings": [],
    }
    f = _Findings()
    metrics: Counter = result["metrics"]

    def timed(stage: str, fn):
        t0 = time.perf_counter()
        try:
            return fn()
        finally:
            result["timings"][stage] = round(time.perf_counter() - t0, 3)

    try:
        text = timed("read", lambda: load_text(root, item))
    except UnicodeDecodeError as exc:
        result["status"] = "rejected"
        result["error"] = _error(exc)
        f.add("not_utf8", "high", item.path, "file is not UTF-8 text; the upload route rejects it")
        result["findings"] = f.items
        return result
    result["input"]["bytes"] = len(text.encode("utf-8"))

    try:
        truth = timed("ground_truth", lambda: build_truth(item, text))
    except Exception as exc:  # the harness's own parser failing is reported, not hidden
        result["status"] = "harness_error"
        result["error"] = _error(exc)
        result["findings"] = f.items
        return result
    if truth is None:
        result["status"] = "not_a_model"
        result["findings"] = f.items
        return result
    result["input"]["format"] = truth.format
    result["features"] = dict(truth.features)
    result["data_sources"] = dict(truth.data_sources)

    # --- Run the analyzer exactly as the upload endpoint does --------------
    from app.db.session import get_session, init_db
    from app.ingestion.service import IngestionError, ingest_json_file
    from app.metadata import store

    init_db()
    session = get_session()
    try:
        project = store.create_project(session, f"harness:{item.path}")
        project_id = project.project.id
        try:
            ingest = timed("ingest", lambda: ingest_json_file(session, project_id, item.upload_filename, text))
        except IngestionError as exc:
            result["status"] = "rejected"
            result["error"] = _error(exc)
            f.add("format_rejected", "critical", item.path,
                  f"the analyzer rejected a valid {truth.format} model", str(exc))
            _count_truth(truth, metrics)
            result["findings"] = f.items
            return result
        except Exception as exc:
            result["status"] = "crashed"
            result["error"] = _error(exc)
            f.add("ingest_crash", "critical", item.path,
                  f"ingestion raised {type(exc).__name__} (the upload would return HTTP 500)",
                  f"{type(exc).__name__}: {_clip(str(exc))}")
            _count_truth(truth, metrics)
            result["findings"] = f.items
            return result

        data = store.get_project_data(session, project_id)
        graph_json = store.get_graph_snapshot(session, project_id)
    finally:
        session.close()

    result["detected_schema"] = ingest["detected_schema"]
    if not data.semantic_models:
        result["status"] = "not_extracted"
        f.add("format_not_recognized", "critical", item.path,
              f"a valid {truth.format} model was detected by the analyzer as "
              f"'{ingest['detected_schema']}' and nothing was extracted")
        _count_truth(truth, metrics)
        result["findings"] = f.items
        return result

    model = data.semantic_models[0]
    timed("compare", lambda: _compare(truth, model, data, f, metrics, result))
    _run_downstream(model, data, graph_json, f, metrics, result, timed)

    result["metrics"] = dict(metrics)
    result["findings"] = f.items
    return result


def _count_truth(truth: TruthModel, metrics: Counter) -> None:
    metrics["tables_truth"] += len(truth.tables)
    metrics["columns_truth"] += sum(len(t.columns) for t in truth.tables.values())
    metrics["measures_truth"] += len(truth.all_measures())
    metrics["relationships_truth"] += len(truth.relationships)


# --- Extraction comparison --------------------------------------------------

def _diff(f: _Findings, metrics: Counter, what: str, truth_keys: list, analyzer_keys: list,
          severity: str, fmt) -> set:
    t, a = Counter(truth_keys), Counter(analyzer_keys)
    matched = t & a
    metrics[f"{what}_truth"] += sum(t.values())
    metrics[f"{what}_analyzer"] += sum(a.values())
    metrics[f"{what}_matched"] += sum(matched.values())
    for key in sorted((t - a).elements(), key=str):
        f.add(f"{what}_missing", severity, fmt(key), f"{what[:-1]} in the source model was not extracted")
    for key in sorted((a - t).elements(), key=str):
        f.add(f"{what}_extra", severity, fmt(key),
              f"analyzer extracted a {what[:-1]} that isn't in the source model (often a mis-parsed name)")
    return set(matched)


def _compare(truth: TruthModel, model, data, f: _Findings, metrics: Counter, result: dict) -> None:
    a_tables = {t.name: t for t in model.tables}

    _diff(f, metrics, "tables", list(truth.tables), [t.name for t in model.tables], "high", str)
    _diff(f, metrics, "columns",
          [(t.name, c) for t in truth.tables.values() for c in t.columns],
          [(t.name, c.name) for t in model.tables for c in t.columns],
          "medium", lambda k: f"{k[0]}[{k[1]}]")
    matched_measures = _diff(
        f, metrics, "measures",
        [(m.table, m.name) for m in truth.all_measures()],
        [(t.name, m.name) for t in model.tables for m in t.measures],
        "high", lambda k: f"{k[0]}[{k[1]}]")

    # Measure expression fidelity: the text everything downstream reads.
    a_measures = {(t.name, m.name): m for t in model.tables for m in t.measures}
    faithful: list = []
    for tm in truth.all_measures():
        am = a_measures.get((tm.table, tm.name))
        if am is None or (tm.table, tm.name) not in matched_measures:
            continue
        if _norm(am.expression) == _norm(tm.expression):
            metrics["measure_expr_faithful"] += 1
            faithful.append((tm, am))
        elif not _norm(am.expression) and _norm(tm.expression):
            f.add("measure_expression_dropped", "high", f"{tm.table}[{tm.name}]",
                  "measure expression is empty after extraction; it is missing from lineage, "
                  "classification and SQL translation",
                  f"source DAX: {_clip(tm.expression)}")
        else:
            f.add("measure_expression_altered", "medium", f"{tm.table}[{tm.name}]",
                  "extracted measure expression differs from the source",
                  f"source: {_clip(tm.expression)}  |  extracted: {_clip(am.expression)}")

    _compare_relationships(truth, model, f, metrics)

    # Teradata lineage: every table whose partition reads Teradata should
    # carry a source hint, since that's the app's only Teradata link.
    for tt in truth.tables.values():
        if not tt.teradata_source:
            continue
        metrics["teradata_tables_truth"] += 1
        at = a_tables.get(tt.name)
        if at is not None and (at.source_hint or "").startswith("Teradata: "):
            metrics["teradata_tables_captured"] += 1
        else:
            f.add("teradata_source_missed", "medium", tt.name,
                  "table reads from Teradata but the analyzer recorded no Teradata source "
                  "(missing from the Teradata Assessment page and lineage)",
                  f"source: {tt.teradata_source}")

    _compare_references(truth, model, data, faithful, f, metrics)


def _compare_relationships(truth: TruthModel, model, f: _Findings, metrics: Counter) -> None:
    a_rels = {(r.from_table, r.from_column, r.to_table, r.to_column): r for r in model.relationships}
    _diff(f, metrics, "relationships",
          [r.key for r in truth.relationships], list(a_rels),
          "high", lambda k: f"{k[0]}[{k[1]}] -> {k[2]}[{k[3]}]")
    for tr in truth.relationships:
        ar = a_rels.get(tr.key)
        if ar is None:
            continue
        label = f"{tr.from_table}[{tr.from_column}] -> {tr.to_table}[{tr.to_column}]"
        metrics["relationship_props_checked"] += 1
        wrong = False
        a_m2m = "MANY_TO_MANY" in (ar.cardinality or "").upper() or "M2M" in (ar.cardinality or "").upper()
        if a_m2m != tr.is_many_to_many:
            wrong = True
            f.add("relationship_cardinality_wrong", "high" if tr.is_many_to_many else "medium", label,
                  "many-to-many flag disagrees with the source; drives M2M migration gaps and "
                  "complexity caps",
                  f"source: {tr.from_cardinality}-to-{tr.to_cardinality}; analyzer: {ar.cardinality}")
        a_bidi = "BOTH" in (ar.cross_filter_direction or "").upper()
        if a_bidi != tr.is_bidirectional:
            wrong = True
            f.add("relationship_crossfilter_wrong", "high" if tr.is_bidirectional else "medium", label,
                  "bi-directional flag disagrees with the source; drives bi-di migration gaps",
                  f"source: {tr.cross_filter}; analyzer: {ar.cross_filter_direction}")
        if ar.is_active != tr.is_active:
            wrong = True
            f.add("relationship_active_wrong", "medium", label, "isActive disagrees with the source",
                  f"source: {tr.is_active}; analyzer: {ar.is_active}")
        if wrong:
            metrics["relationship_props_wrong"] += 1
        if tr.is_many_to_many:
            metrics["m2m_truth"] += 1
        if tr.is_bidirectional:
            metrics["bidi_truth"] += 1


_FALSE_GAP_REASONS = {
    "case": "name differs only in letter case (DAX names are case-insensitive)",
    "column_other_table": "bare [Column] from another table, valid in an iterator's row context",
    "virtual_column": "column defined inside the expression (ADDCOLUMNS / SUMMARIZE / SELECTCOLUMNS)",
    "qualified_measure": "Table[Measure] where the measure lives on a different table",
    "other": "the reference resolves to a real model object",
}


def _compare_references(truth, model, data, faithful, f: _Findings, metrics: Counter) -> None:
    resolver = Resolver(truth)

    # Analyzer's unresolved-reference gaps, keyed by measure.
    gaps_by_measure: dict[str, list[Ref]] = {}
    for gap in data.gaps:
        parsed = parse_analyzer_gap(gap.missing_information)
        if parsed:
            gaps_by_measure.setdefault(parsed[0], []).append(parsed[1])

    for tm, am in faithful:
        obj = f"{tm.table}[{tm.name}]"
        refs, strings = scan(tm.expression)
        resolved = {r: resolver.resolve(r, tm.table, strings) for r in refs}

        for gref in gaps_by_measure.get(tm.name, []):
            metrics["analyzer_gaps"] += 1
            match = [r for r in refs if r.name == gref.name and (r.table or None) == (gref.table or None)]
            label = f"{gref.table or ''}[{gref.name}]"
            if not match:
                metrics["analyzer_false_gaps"] += 1
                f.add("phantom_reference", "medium", obj,
                      "analyzer reported an unresolved reference that is not a reference at all "
                      "(text inside a comment or string, or a mis-tokenized escape)",
                      f"{label} in: {_clip(tm.expression)}")
                continue
            res = resolved[match[0]]
            if res.kind == "unresolved":
                metrics["gaps_confirmed"] += 1
                continue
            metrics["analyzer_false_gaps"] += 1
            if not res.exact_case:
                reason = "case"
            elif res.kind in ("column_other_table", "virtual_column"):
                reason = res.kind
            elif res.kind == "measure" and gref.table is not None:
                reason = "qualified_measure"
            else:
                reason = "other"
            f.add(f"false_gap:{reason}", "medium", obj,
                  f"analyzer reported an unresolved reference, but {_FALSE_GAP_REASONS[reason]}",
                  f"{label} -> {res.target or res.kind}")

        # Lineage completeness: measure->measure and measure->column edges.
        h_edges = {res.target.lower(): res.target for res in resolved.values()
                   if res.target and res.target != tm.name
                   and res.kind in ("measure", "column", "column_other_table")}
        a_edges = {e.lower() for e in am.referenced_measures + am.referenced_columns}
        metrics["lineage_edges_truth"] += len(h_edges)
        metrics["lineage_edges_matched"] += len(h_edges.keys() & a_edges)
        missed = sorted(h_edges[k] for k in h_edges.keys() - a_edges)
        if missed:
            f.add("lineage_edge_missed", "medium", obj,
                  "measure depends on objects the analyzer's lineage graph doesn't link it to",
                  "missing: " + ", ".join(missed[:8]) + (" …" if len(missed) > 8 else ""))

        unresolved = sorted({f"{r.table or ''}[{r.name}]" for r, res in resolved.items() if res.kind == "unresolved"})
        if unresolved:
            metrics["refs_unresolved_in_source"] += len(unresolved)
            f.add("unresolved_in_source", "info", obj,
                  "references nothing in the model per the harness too (broken measure, "
                  "calculation-group / field-parameter construct, or harness limitation)",
                  ", ".join(unresolved[:8]))


# --- Downstream generators ---------------------------------------------------

_DAX_ONLY_FUNCS = {
    "CALCULATE", "CALCULATETABLE", "FILTER", "ALL", "ALLEXCEPT", "ALLSELECTED", "REMOVEFILTERS",
    "KEEPFILTERS", "SELECTEDVALUE", "HASONEVALUE", "ISBLANK", "BLANK", "DIVIDE", "COUNTROWS",
    "RELATED", "RELATEDTABLE", "VALUES", "SUMX", "AVERAGEX", "MINX", "MAXX", "COUNTX", "SWITCH",
    "FORMAT", "EOMONTH", "USERELATIONSHIP", "TREATAS", "CONCATENATE", "CONCATENATEX", "MID",
    "SUBSTITUTE", "SEARCH", "FIND", "TRUE", "FALSE", "AND", "OR", "LOOKUPVALUE", "ISFILTERED",
    "SELECTEDMEASURE", "DATEADD", "TOTALYTD", "SAMEPERIODLASTYEAR", "COUNTBLANK", "DISTINCTCOUNT",
}
_DAX_ONLY_RE = re.compile(r"\b(" + "|".join(sorted(_DAX_ONLY_FUNCS)) + r")\s*\(", re.I)
_SEMANTIC_RISKS = [
    (re.compile(r"\bint\s*\(", re.I), "INT: DAX rounds down (floor); Databricks int() truncates toward zero"),
    (re.compile(r"\blog\s*\(", re.I), "LOG: DAX is LOG(number, base=10); Databricks is log(base, expr) and "
                                       "single-argument log() is natural log"),
    (re.compile(r"\bweekday\s*\(", re.I), "WEEKDAY: DAX defaults to 1=Sunday; Databricks weekday() is 0=Monday"),
    (re.compile(r"\btrim\s*\(", re.I), "TRIM: DAX also collapses internal runs of spaces; Databricks trim() doesn't"),
]
_STRING_LITERALS_RE = re.compile(r'"(?:[^"]|"")*"')


def _operator_risks(dax: str, sql: str) -> list[str]:
    """DAX & / && / || carried into SQL unchanged. Compared outside string
    literals: & concatenates in DAX but is bitwise AND in Databricks, and
    DAX's logical || is string concatenation in Databricks."""
    dax_code, sql_code = _STRING_LITERALS_RE.sub('""', dax), _STRING_LITERALS_RE.sub('""', sql)
    risks = []
    if "&&" in sql_code:
        risks.append("&&: DAX logical AND left in SQL")
    if re.search(r"(?<!&)&(?!&)", sql_code):
        risks.append("&: DAX string concatenation; in Databricks & is bitwise AND")
    dax_concats = len(re.findall(r"(?<!&)&(?!&)", dax_code))
    if dax_code.count("||") and sql_code.count("||") > dax_concats:
        risks.append("||: DAX logical OR left in SQL, where || is string concatenation")
    return risks


def _two_arg_min_max(dax: str) -> bool:
    """DAX MIN(a, b)/MAX(a, b) is a scalar comparison; SQL min/max are
    one-argument aggregates (the equivalent is least/greatest)."""
    for m in re.finditer(r"\b(MIN|MAX)\s*\(", dax, re.I):
        depth, i, commas = 0, m.end() - 1, 0
        while i < len(dax):
            ch = dax[i]
            if ch in "({":
                depth += 1
            elif ch in ")}":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "," and depth == 1:
                commas += 1
            i += 1
        if commas == 1:
            return True
    return False


def _run_downstream(model, data, graph_json, f: _Findings, metrics: Counter, result: dict, timed) -> None:
    from app.parsers.dax.classifier import KNOWN

    result["bands"] = dict(Counter(m.complexity_band for t in model.tables for m in t.measures))
    unknown = Counter(fn for t in model.tables for m in t.measures for fn in m.functions_used if fn not in KNOWN)
    result["unknown_functions"] = dict(unknown)

    def stage(name: str, fn):
        try:
            return timed(name, fn)
        except Exception as exc:
            f.add(f"stage_crash:{name}", "high", name,
                  f"{name} raised {type(exc).__name__}; that page/endpoint would return HTTP 500",
                  f"{type(exc).__name__}: {str(exc)[:300]}")
            result.setdefault("stage_errors", {})[name] = _error(exc)
            return None

    from app.migration.plan import build_phase_plan
    from app.metadata.aggregates import compute_dashboard
    from app.parsers.dax.sql_translator import translate_model
    from app.recommendations.gold_design import detect_fact_groups
    from app.recommendations.metric_view_yaml import build_metric_view_specs, render_yaml
    from app.recommendations.wrapper_views import build_wrapper_views
    from app.reporting.blueprint import build_report
    from app.reporting.exporters import render_docx, render_pdf

    items = stage("sql_translation", lambda: translate_model(model)) or []
    result["translation_statuses"] = dict(Counter(i.status for i in items))
    for it in items:
        if it.status not in ("auto", "auto_spot_check"):
            continue
        prefix = "auto" if it.status == "auto" else "spot_check"
        sev = "high" if it.status == "auto" else "low"
        metrics[f"{prefix}_translations"] += 1
        problems: list[tuple[str, str]] = []
        err = _sql_error(f"SELECT {it.translated_sql}")
        if err:
            problems.append(("invalid_sql", f"does not parse as Databricks SQL: {err}"))
        residue = _DAX_ONLY_RE.findall(it.translated_sql)
        if residue or re.search(r"\[[^\]]*\]", it.translated_sql):
            problems.append(("dax_residue", "DAX left in output: " +
                             ", ".join(sorted({r.upper() for r in residue}) or ["[bracket reference]"])))
        for rx, why in _SEMANTIC_RISKS:
            if rx.search(it.translated_sql):
                problems.append(("semantic_risk", why))
        for why in _operator_risks(it.original_dax, it.translated_sql):
            problems.append(("semantic_risk", why))
        if _two_arg_min_max(it.original_dax):
            problems.append(("semantic_risk", "two-argument MIN/MAX is scalar in DAX; needs least()/greatest()"))
        if problems:
            metrics[f"{prefix}_translations_flagged"] += 1
        for kind, why in problems:
            f.add(f"translation_{kind}", sev, f"{it.table_name}[{it.measure_name}]",
                  f"{it.status} translation: {why.split(':')[0] if kind == 'invalid_sql' else why}",
                  f"DAX: {_clip(it.original_dax)}  |  SQL: {_clip(it.translated_sql)}"
                  + (f"  |  {why}" if kind == "invalid_sql" else ""))

    stage("gold_design", lambda: detect_fact_groups(model))
    specs = stage("metric_view", lambda: build_metric_view_specs(model)) or []
    for spec in specs:
        rendered = stage("metric_view_yaml", lambda: render_yaml(spec))
        if rendered is None:
            continue
        try:
            import yaml
            yaml.safe_load(rendered)
        except Exception as exc:
            f.add("metric_view_yaml_invalid", "high", spec.fact_table, "generated Metric View YAML doesn't parse",
                  str(exc)[:300])
        for meas in spec.measures:
            err = _sql_error(f"SELECT {meas.expr}")
            if err:
                f.add("metric_view_measure_invalid_sql", "high", f"{spec.fact_table}[{meas.name}]",
                      "Metric View measure expr doesn't parse as Databricks SQL", f"{meas.expr[:300]}  |  {err}")
    wrappers = stage("wrapper_views", lambda: build_wrapper_views(model)) or []
    for w in wrappers:
        err = _sql_error(w.sql)
        if err:
            f.add("wrapper_view_invalid_sql", "high", w.fact_table, "generated wrapper view doesn't parse",
                  err)
    stage("dashboard", lambda: compute_dashboard(data))
    stage("migration_plan", lambda: build_phase_plan(data))
    graph_summary = json.loads(graph_json) if graph_json and graph_json != "{}" else {"nodes": [], "edges": []}
    report = stage("assessment_report", lambda: build_report(data, graph_summary))
    if report is not None:
        stage("export_pdf", lambda: render_pdf(report))
        stage("export_docx", lambda: render_docx(report))


def _sql_error(sql: str) -> str | None:
    import sqlglot
    from sqlglot.errors import ParseError, TokenError

    try:
        sqlglot.parse(sql, read="databricks")
    except (ParseError, TokenError) as exc:
        return str(exc).splitlines()[0][:200]
    return None


# --- Subprocess entry point -------------------------------------------------

def child_main(root: str, item: InputItem, conn) -> None:
    tmp = tempfile.mkdtemp(prefix="migration-harness-")
    os.environ["MIGRATION_ANALYZER_DB"] = os.path.join(tmp, "harness.db")
    try:
        result = analyze(Path(root), item)
    except Exception as exc:
        result = {"input": {"path": item.path, "kind": item.kind, "notes": item.notes},
                  "status": "harness_error", "error": _error(exc), "findings": []}
    conn.send(result)
    conn.close()
