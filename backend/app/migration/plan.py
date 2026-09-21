"""Builds the phased migration plan (spec section 26). The nine phases and
their task lists are fixed by the spec; what Milestone 1 can determine is
only each phase's status given what's actually been ingested so far — it
never invents Teradata/Databricks progress that hasn't happened.
"""
from __future__ import annotations

from app.metadata.models import MigrationPhase, ProjectData, Status

_NEEDS_TERADATA = "Requires Teradata SQL/DDL ingestion, which is not yet implemented."
_NEEDS_DATABRICKS_ENGINE = "Requires the Databricks migration engine, which is not yet implemented."


def build_phase_plan(data: ProjectData) -> list[MigrationPhase]:
    has_powerbi_data = len(data.semantic_models) > 0

    return [
        MigrationPhase(
            key="discovery",
            name="Phase 1 — Discovery",
            status=Status.CONFIRMED if has_powerbi_data else Status.REQUIRES_INPUT,
            tasks=[
                "Power BI inventory",
                "Semantic-model extraction",
                "Teradata dependency identification",
                "Missing metadata identification",
            ],
            blocked_reason=None if has_powerbi_data else "No Power BI metadata has been ingested yet.",
        ),
        MigrationPhase(
            key="teradata_assessment",
            name="Phase 2 — Teradata Assessment",
            status=Status.REQUIRES_INPUT,
            tasks=[
                "Resolve views",
                "Identify base tables",
                "Analyze transformations",
                "Identify incremental strategies",
            ],
            blocked_reason=_NEEDS_TERADATA,
        ),
        MigrationPhase(
            key="bronze",
            name="Phase 3 — Bronze",
            status=Status.REQUIRES_INPUT,
            tasks=["Ingest source data", "Create Delta tables", "Implement CDC/incremental processing"],
            blocked_reason=_NEEDS_TERADATA,
        ),
        MigrationPhase(
            key="silver",
            name="Phase 4 — Silver",
            status=Status.REQUIRES_INPUT,
            tasks=["Clean", "Normalize", "Deduplicate", "Conform", "Implement business transformations"],
            blocked_reason=_NEEDS_DATABRICKS_ENGINE,
        ),
        MigrationPhase(
            key="gold",
            name="Phase 5 — Gold",
            status=Status.REQUIRES_INPUT,
            tasks=["Create facts", "Create dimensions", "Create bridges", "Create aggregates"],
            blocked_reason=_NEEDS_DATABRICKS_ENGINE,
        ),
        MigrationPhase(
            key="power_bi_migration",
            name="Phase 6 — Power BI",
            status=Status.REQUIRES_INPUT,
            tasks=[
                "Replace Teradata connections",
                "Connect Power BI to Databricks SQL Warehouse",
                "Preserve appropriate semantic logic",
            ],
            blocked_reason="Requires a deployed Databricks Gold layer to point Power BI at.",
        ),
        MigrationPhase(
            key="validation",
            name="Phase 7 — Validation",
            status=Status.REQUIRES_INPUT,
            tasks=["Validate data", "Validate relationships", "Validate measures", "Validate reports", "Validate performance"],
            blocked_reason="Requires the validation framework, which is not yet implemented.",
        ),
        MigrationPhase(
            key="parallel_run",
            name="Phase 8 — Parallel Run",
            status=Status.REQUIRES_INPUT,
            tasks=["Run Teradata and Databricks solutions together", "Compare outputs"],
            blocked_reason="Requires a deployed Databricks target to run in parallel with Teradata.",
        ),
        MigrationPhase(
            key="cutover",
            name="Phase 9 — Cutover",
            status=Status.REQUIRES_INPUT,
            tasks=["Production deployment", "Monitoring", "Teradata retirement after approval"],
            blocked_reason="Requires a validated, parallel-run-approved Databricks target.",
        ),
    ]
