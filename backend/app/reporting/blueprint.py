"""Builds the Migration Assessment Report (spec section 13's blueprint
document, condensed) from whatever the canonical model currently holds.

Milestone 1 only ingests Power BI JSON, so sections that depend on
Teradata/Databricks/SQL/M ingestion or the recommendation engine (none of
which exist yet) are rendered with status=REQUIRES_INPUT and a plain-English
reason, rather than fabricated or silently omitted. Sections backed by real
canonical data (Power BI inventory, DAX dependencies, migration gaps,
cross-model overlap) are computed for real.
"""
from __future__ import annotations

from app.metadata.aggregates import compute_dashboard
from app.metadata.models import AssessmentReport, ProjectData, ReportSection, Status
from app.parsers.dax.sql_translator import translate_model
from app.recommendations.gold_design import detect_fact_groups
from app.recommendations.metric_view_yaml import build_metric_view_specs
from app.recommendations.wrapper_views import build_wrapper_views

# Spec section 13 lists 35 blueprint sections. Sections with real logic below
# are removed from this list; everything left here is rendered as a
# placeholder naming what future milestone would confirm it.
_DEFERRED_SECTIONS: list[tuple[str, str, str]] = [
    ("power_query_analysis", "Power Query Analysis", "Requires Power Query / M parsing (not yet implemented)."),
    ("teradata_inventory", "Teradata Inventory", "Requires Teradata SQL/DDL ingestion (not yet implemented)."),
    ("teradata_dependency_analysis", "Teradata Dependency Analysis", "Requires Teradata SQL/DDL ingestion (not yet implemented)."),
    ("source_to_target_mapping", "Source-to-Target Mapping", "Requires Teradata ingestion and Databricks target design."),
    ("databricks_target_architecture", "Databricks Target Architecture", "Requires the Databricks migration engine (not yet implemented)."),
    ("bronze_design", "Bronze Design", "Requires Teradata base-table discovery and the Databricks migration engine."),
    ("silver_design", "Silver Design", "Requires the Databricks migration engine (not yet implemented)."),
    ("fact_grain_definitions", "Fact Grain Definitions", "Requires a real source key — Power BI metadata alone can't confirm grain."),
    ("power_bi_migration_strategy", "Power BI Migration Strategy", "Requires the DAX classification engine (KEEP_IN_POWER_BI / CANDIDATE_FOR_DATABRICKS)."),
    ("data_quality_strategy", "Data Quality Strategy", "Requires the data-quality rule generator (not yet implemented)."),
    ("validation_strategy", "Validation Strategy", "Requires the validation framework (not yet implemented)."),
    ("performance_strategy", "Performance Strategy", "Requires Teradata/DAX performance analysis (not yet implemented)."),
    ("security_strategy", "Security Strategy", "Requires RLS/OLS extraction and Unity Catalog mapping (not yet implemented)."),
    ("cicd_strategy", "CI/CD Strategy", "Not yet scoped."),
    ("migration_complexity", "Migration Complexity", "Requires the complexity classification engine (not yet implemented)."),
    ("dependency_aware_sequence", "Dependency-Aware Migration Sequence", "Requires Teradata/Databricks dependency data."),
    ("parallel_run", "Parallel Run", "Requires a deployed Databricks target to compare against."),
    ("cutover_plan", "Cutover Plan", "Requires a completed migration to plan cutover for."),
    ("rollback_plan", "Rollback Plan", "Requires a completed migration to plan rollback for."),
    ("risks", "Risks", "Requires broader project context than current metadata provides."),
    ("assumptions", "Assumptions", "Requires broader project context than current metadata provides."),
]


def build_report(data: ProjectData, graph_summary: dict) -> AssessmentReport:
    dashboard = compute_dashboard(data)
    tables = [t for m in data.semantic_models for t in m.tables]
    measures = [meas for t in tables for meas in t.measures]

    sections: list[ReportSection] = []

    sections.append(_migration_scope_section(data))
    sections.append(_current_state_architecture_section(dashboard))
    sections.append(_powerbi_inventory_section(tables))
    sections.append(_dax_analysis_section(measures))
    sections.append(_cross_report_section(data))
    sections.append(_lineage_section(graph_summary))
    sections.append(_migration_gaps_section(data))
    sections.append(_gold_design_section(data))
    sections.append(_sql_conversion_section(data))
    sections.append(_open_questions_section(data))

    for key, title, reason in _DEFERRED_SECTIONS:
        sections.append(
            ReportSection(key=key, title=title, status=Status.REQUIRES_INPUT, summary=reason)
        )

    return AssessmentReport(
        project_name=data.project.name,
        executive_summary=dashboard,
        sections=sections,
    )


def _migration_scope_section(data: ProjectData) -> ReportSection:
    details = [f"{a.filename} — detected as {a.detected_schema}" for a in data.project.source_artifacts]
    return ReportSection(
        key="migration_scope",
        title="Migration Scope & Input Artifacts",
        status=Status.CONFIRMED if data.project.source_artifacts else Status.REQUIRES_INPUT,
        summary=f"{len(data.project.source_artifacts)} file(s) ingested for project '{data.project.name}'.",
        details=details or ["No files ingested yet."],
    )


def _current_state_architecture_section(dashboard: dict) -> ReportSection:
    return ReportSection(
        key="current_state_architecture",
        title="Current-State Architecture",
        status=Status.CONFIRMED if dashboard["semantic_models"] else Status.REQUIRES_INPUT,
        summary=(
            f"{dashboard['semantic_models']} Power BI semantic model(s), {dashboard['tables']} table(s), "
            f"{dashboard['measures']} measure(s), {dashboard['relationships']} relationship(s) discovered. "
            "Teradata and Databricks layers are not yet represented (no Teradata/Databricks input has been ingested)."
        ),
    )


def _powerbi_inventory_section(tables) -> ReportSection:
    details = [f"{t.name} — {len(t.columns)} column(s), {len(t.measures)} measure(s)" for t in tables]
    return ReportSection(
        key="powerbi_inventory",
        title="Power BI Inventory & Semantic Model Analysis",
        status=Status.CONFIRMED if tables else Status.REQUIRES_INPUT,
        summary=f"{len(tables)} table(s) across all ingested semantic models.",
        details=details,
    )


def _dax_analysis_section(measures) -> ReportSection:
    if not measures:
        return ReportSection(
            key="dax_analysis",
            title="DAX Analysis",
            status=Status.REQUIRES_INPUT,
            summary="No measures ingested yet.",
        )
    max_depth = max((m.dependency_depth for m in measures), default=0)
    chained = [m for m in measures if m.referenced_measures]
    details = [
        f"{m.name} (depth {m.dependency_depth}) -> {', '.join(m.referenced_measures)}"
        for m in chained
    ]
    band_counts: dict[str, int] = {}
    for m in measures:
        band_counts[m.complexity_band] = band_counts.get(m.complexity_band, 0) + 1
    band_summary = ", ".join(f"{count} {band}" for band, count in sorted(band_counts.items()))
    manual_port = [m for m in measures if m.complexity_band in ("MANUAL_PORT", "UNSUPPORTED")]
    complexity_details = [
        f"{m.name}: score {m.complexity_score} ({m.complexity_category}) — {'; '.join(m.complexity_reasons) or 'no deductions'}"
        for m in manual_port
    ]
    return ReportSection(
        key="dax_analysis",
        title="DAX Analysis",
        status=Status.CONFIRMED,
        summary=(
            f"{len(measures)} measure(s) analyzed; max dependency depth {max_depth}; "
            f"{len(chained)} measure(s) reference other measures. Migration-complexity "
            f"classification: {band_summary}."
        ),
        details=details + complexity_details,
    )


def _cross_report_section(data: ProjectData) -> ReportSection:
    if len(data.semantic_models) < 2:
        return ReportSection(
            key="cross_report_analysis",
            title="Cross-Report Dependency Analysis",
            status=Status.REQUIRES_INPUT,
            summary="Only one semantic model ingested — nothing to compare across reports yet.",
        )
    table_to_models: dict[str, set[str]] = {}
    for model in data.semantic_models:
        for table in model.tables:
            table_to_models.setdefault(table.name, set()).add(model.name)
    shared = {name: models for name, models in table_to_models.items() if len(models) > 1}
    details = [f"{name} — used by {', '.join(sorted(models))}" for name, models in shared.items()]
    return ReportSection(
        key="cross_report_analysis",
        title="Cross-Report Dependency Analysis",
        status=Status.INFERRED if shared else Status.CONFIRMED,
        summary=(
            f"{len(shared)} table name(s) shared across {len(data.semantic_models)} semantic models "
            "(matched by name — a later milestone should confirm these resolve to the same source object)."
            if shared
            else f"No shared table names found across the {len(data.semantic_models)} ingested semantic models."
        ),
        details=details,
    )


def _lineage_section(graph_summary: dict) -> ReportSection:
    nodes = graph_summary.get("nodes", [])
    edges = graph_summary.get("edges", [])
    return ReportSection(
        key="end_to_end_lineage",
        title="End-to-End Lineage",
        status=Status.CONFIRMED if nodes else Status.REQUIRES_INPUT,
        summary=(
            f"{len(nodes)} lineage node(s) and {len(edges)} edge(s) built from Power BI metadata "
            "(semantic model -> table -> column/measure). Teradata and Databricks lineage stages are "
            "not yet connected."
        ),
    )


def _migration_gaps_section(data: ProjectData) -> ReportSection:
    details = [f"{g.object_ref}: {g.missing_information}" for g in data.gaps]
    return ReportSection(
        key="migration_gaps",
        title="Migration Gaps",
        status=Status.CONFIRMED,
        summary=f"{len(data.gaps)} gap(s) identified from ingested metadata.",
        details=details,
    )


def _gold_design_section(data: ProjectData) -> ReportSection:
    facts, dimensions = [], []
    for model in data.semantic_models:
        model_facts, model_dimensions = detect_fact_groups(model)
        facts.extend(model_facts)
        dimensions.extend(model_dimensions)

    if not facts:
        return ReportSection(
            key="gold_design",
            title="Gold Design — Candidate Facts & Dimensions",
            status=Status.REQUIRES_INPUT,
            summary="No Power BI semantic model ingested yet, so no candidate fact/dimension tables could be inferred.",
        )

    metric_views = [spec for model in data.semantic_models for spec in build_metric_view_specs(model)]
    wrapper_views = [spec for model in data.semantic_models for spec in build_wrapper_views(model)]

    details = [f"FACT {f.table_name}: {len(f.measures)} measure(s) — {'; '.join(f.evidence)}" for f in facts]
    details += [
        f"DIMENSION {d.table_name}: related to {', '.join(d.related_fact_tables)}" for d in dimensions
    ]
    details += [
        f"METRIC VIEW {spec.fact_table}: {len(spec.measures)} measure(s) included, "
        f"{len(spec.excluded_measures)} excluded, {len(spec.joins)} join(s), {len(spec.dimensions)} dimension(s)"
        for spec in metric_views
    ]
    details += [
        f"WRAPPER VIEW {spec.fact_table}: {len(spec.wrapped_measures)} measure(s) wrapped "
        f"({', '.join(w.pattern for w in spec.wrapped_measures)}), {len(spec.skipped_measures)} skipped"
        + (f", date dimension {spec.date_dimension}" if spec.date_dimension else "")
        for spec in wrapper_views
    ]
    total_wrapped = sum(len(s.wrapped_measures) for s in wrapper_views)
    return ReportSection(
        key="gold_design",
        title="Gold Design — Candidate Facts, Dimensions, Metric Views & Wrapper Views",
        status=Status.INFERRED,
        summary=(
            f"{len(facts)} candidate fact table(s), {len(dimensions)} candidate dimension table(s), "
            f"{len(metric_views)} provisional Metric View YAML spec(s), and {total_wrapped} measure(s) "
            f"covered by {len(wrapper_views)} wrapper view(s) generated from Power BI DAX patterns and "
            "relationships. Fact grain, bridge tables, and aggregates still require Teradata source "
            "data and the Databricks migration engine, neither of which exists yet; every source: "
            "value is a placeholder pending real Unity Catalog names."
        ),
        details=details,
    )


def _sql_conversion_section(data: ProjectData) -> ReportSection:
    items = [i for model in data.semantic_models for i in translate_model(model)]
    if not items:
        return ReportSection(
            key="sql_conversion_requirements",
            title="SQL Conversion Requirements",
            status=Status.REQUIRES_INPUT,
            summary="No measures ingested yet, so no DAX -> Databricks SQL translation could be attempted.",
        )
    status_counts: dict[str, int] = {}
    for i in items:
        status_counts[i.status] = status_counts.get(i.status, 0) + 1
    status_summary = ", ".join(f"{count} {status}" for status, count in sorted(status_counts.items()))
    needs_attention = [i for i in items if i.status not in ("auto", "auto_spot_check")]
    details = [f"{i.measure_name} ({i.status}): {'; '.join(i.notes) or i.translated_sql}" for i in needs_attention]
    return ReportSection(
        key="sql_conversion_requirements",
        title="SQL Conversion Requirements",
        status=Status.INFERRED,
        summary=(
            f"{len(items)} Power BI measure(s) translated toward Databricks SQL: {status_summary}. "
            "Teradata SQL -> Databricks SQL conversion still requires Teradata ingestion, which is "
            "not implemented yet."
        ),
        details=details,
    )


def _open_questions_section(data: ProjectData) -> ReportSection:
    details = [g.recommended_action for g in data.gaps]
    details.append("What Teradata source systems feed each Power BI table? (requires Teradata ingestion)")
    details.append("What is the target Databricks catalog/schema naming convention?")
    return ReportSection(
        key="open_questions",
        title="Open Questions",
        status=Status.REQUIRES_INPUT,
        summary="Questions that must be answered before migration planning can proceed further.",
        details=details,
    )
