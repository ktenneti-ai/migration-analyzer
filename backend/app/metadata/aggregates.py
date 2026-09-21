"""Shared computed-metric logic, used by both the dashboard API and the
assessment report so the two never drift apart."""
from __future__ import annotations

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

    return {
        "reports": 0,  # report-level metadata requires PBIX ingestion (future milestone)
        "semantic_models": len(data.semantic_models),
        "tables": len(tables),
        "columns": sum(len(t.columns) for t in tables),
        "measures": len(measures),
        "relationships": len(relationships),
        "teradata_views": 0,
        "teradata_base_tables": 0,
        "bronze_tables": 0,
        "silver_tables": 0,
        "gold_facts": 0,
        "gold_dimensions": 0,
        "migration_gaps": len(data.gaps),
        "complexity": complexity,
    }
