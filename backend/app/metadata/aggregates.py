"""Shared computed-metric logic, used by both the dashboard API and the
assessment report so the two never drift apart."""
from __future__ import annotations

from app.ingestion.tmdl.tmdl_adapter import TERADATA_SOURCE_HINT_PREFIX, parse_teradata_source_hint
from app.metadata.models import ProjectData
from app.parsers.dax.classifier import complexity_bucket


def compute_dashboard(data: ProjectData) -> dict:
    all_tables = [t for m in data.semantic_models for t in m.tables]
    # Power BI's Auto Date/Time feature generates hidden GUID-suffixed
    # calendar tables per date column (see tmdl_adapter.py's display_name
    # assignment — it's the only thing that ever sets display_name). Power BI
    # Desktop's own model view never counts these as real tables, so neither
    # does this assessment; counting them would overstate the model's size
    # and disagree with what the user sees in Power BI itself.
    tables = [t for t in all_tables if t.display_name is None]
    system_table_names = {t.name for t in all_tables if t.display_name is not None}
    measures = [meas for t in tables for meas in t.measures]
    relationships = [
        r
        for m in data.semantic_models
        for r in m.relationships
        if r.from_table not in system_table_names and r.to_table not in system_table_names
    ]

    complexity = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for measure in measures:
        complexity[complexity_bucket(measure.complexity_band)] += 1

    # No Teradata SQL/DDL ingestion pipeline exists yet, but every table's
    # source_hint (from its TMDL partition's M query — see tmdl_adapter.py)
    # already names its real upstream Teradata object, so "how many Teradata
    # objects do we know about" has a real answer today even without that
    # pipeline; see also app/api/routes/teradata.py, which computes the same
    # split for its own per-row detail. teradata_views/teradata_base_tables
    # are classified from the referenced objects' own "V_" naming
    # convention (confirmed business rule, not an app-invented guess).
    teradata_hints = [
        parse_teradata_source_hint(t.source_hint)
        for t in tables
        if t.source_hint and t.source_hint.startswith(TERADATA_SOURCE_HINT_PREFIX)
    ]
    teradata_referenced = len(teradata_hints)
    teradata_unresolved = len(tables) - teradata_referenced
    teradata_views = sum(1 for h in teradata_hints if h["object_type"] == "VIEW")
    teradata_base_tables = sum(1 for h in teradata_hints if h["object_type"] == "BASE_TABLE")

    return {
        "reports": 0,  # report-level metadata requires PBIX ingestion (future milestone)
        "semantic_models": len(data.semantic_models),
        "tables": len(tables),
        "columns": sum(len(t.columns) for t in tables),
        "measures": len(measures),
        "relationships": len(relationships),
        "teradata_views": teradata_views,
        "teradata_base_tables": teradata_base_tables,
        "teradata_referenced_objects": teradata_referenced,
        "teradata_unresolved_objects": teradata_unresolved,
        "bronze_tables": 0,
        "silver_tables": 0,
        "gold_facts": 0,
        "gold_dimensions": 0,
        "migration_gaps": len(data.gaps),
        "complexity": complexity,
    }
