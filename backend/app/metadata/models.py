"""Canonical metadata model.

Every ingestion adapter (JSON, PBIX, TMDL, SQL, ...) normalizes into these
objects. Nothing here is format-specific. Every extracted or inferred fact
carries a Status and a Provenance record so the UI can always show where a
value came from, and so missing information is represented explicitly as
REQUIRES_INPUT rather than silently omitted or fabricated.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _AllowsModelId(BaseModel):
    """Base for canonical objects with a `model_id` field, which otherwise
    collides with pydantic's protected `model_` namespace."""

    model_config = ConfigDict(protected_namespaces=())


class Status(str, Enum):
    CONFIRMED = "CONFIRMED"
    INFERRED = "INFERRED"
    REQUIRES_INPUT = "REQUIRES_INPUT"


class Provenance(BaseModel):
    source_file: str
    source_type: str
    json_path: Optional[str] = None
    extracted_at: datetime = Field(default_factory=utcnow)


class SourceArtifact(BaseModel):
    id: str
    filename: str
    file_type: str
    uploaded_at: datetime = Field(default_factory=utcnow)
    raw_schema_summary: Optional[str] = None
    detected_schema: str = "unknown_generic"


class Project(BaseModel):
    id: str
    name: str
    created_at: datetime = Field(default_factory=utcnow)
    source_artifacts: list[SourceArtifact] = Field(default_factory=list)


class PowerBIColumn(BaseModel):
    id: str
    table_id: str
    name: str
    data_type: Optional[str] = None
    is_calculated: bool = False
    expression: Optional[str] = None
    hidden: bool = False
    status: Status = Status.CONFIRMED
    provenance: Provenance


class PowerBIMeasure(BaseModel):
    id: str
    table_id: str
    name: str
    expression: str
    referenced_measures: list[str] = Field(default_factory=list)
    referenced_columns: list[str] = Field(default_factory=list)
    dependent_tables: list[str] = Field(default_factory=list)
    dependency_depth: int = 0
    status: Status = Status.CONFIRMED
    provenance: Provenance

    # Migration-complexity classification (backend/app/parsers/dax/classifier.py),
    # adapted from the pbi-unified skill's classify_score.py methodology.
    functions_used: list[str] = Field(default_factory=list)
    complexity_score: int = 100
    complexity_band: str = "AUTO"  # AUTO | AUTO_SPOT_CHECK | NEEDS_REVIEW | MANUAL_PORT | UNSUPPORTED
    complexity_category: str = "A"  # A-F, see classifier.py docstring
    complexity_reasons: list[str] = Field(default_factory=list)


class PowerBITable(_AllowsModelId):
    id: str
    model_id: str
    name: str
    table_type: str = "REGULAR"
    source_hint: Optional[str] = None
    columns: list[PowerBIColumn] = Field(default_factory=list)
    measures: list[PowerBIMeasure] = Field(default_factory=list)
    status: Status = Status.CONFIRMED
    provenance: Provenance


class PowerBIRelationship(_AllowsModelId):
    id: str
    model_id: str
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cardinality: str = "REQUIRES_INPUT"
    cross_filter_direction: str = "REQUIRES_INPUT"
    is_active: bool = True
    status: Status = Status.CONFIRMED
    provenance: Provenance


class PowerBISemanticModel(BaseModel):
    id: str
    project_id: str
    name: str
    tables: list[PowerBITable] = Field(default_factory=list)
    relationships: list[PowerBIRelationship] = Field(default_factory=list)
    status: Status = Status.CONFIRMED
    provenance: Provenance


# --- Skeleton canonical objects for later milestones (Teradata / Databricks). ---
# These exist now so the canonical model doesn't need reshaping later (spec section 3):
# one model, populated incrementally as more ingestion adapters are added.

class TeradataTable(BaseModel):
    id: str
    database: str
    schema_name: str
    name: str
    object_type: str = "TABLE"
    sql: Optional[str] = None
    status: Status = Status.REQUIRES_INPUT
    provenance: Optional[Provenance] = None


class DatabricksTable(BaseModel):
    id: str
    catalog: str
    schema_name: str
    name: str
    layer: str = "REQUIRES_INPUT"  # bronze | silver | gold
    status: Status = Status.REQUIRES_INPUT
    provenance: Optional[Provenance] = None


class GoldFactCandidate(BaseModel):
    """A Power BI table inferred to be a Gold-layer fact table candidate
    (backend/app/recommendations/gold_design.py), adapted from the
    pbi-unified skill's translate.py detect_fact_group() heuristic."""

    table_name: str
    status: Status = Status.INFERRED
    evidence: list[str] = Field(default_factory=list)
    measures: list[str] = Field(default_factory=list)
    grain: str = (
        "REQUIRES_INPUT — grain cannot be determined from Power BI metadata alone; "
        "confirm the natural/business key with the data owner or the Teradata source."
    )


class GoldDimensionCandidate(BaseModel):
    table_name: str
    status: Status = Status.INFERRED
    evidence: list[str] = Field(default_factory=list)
    related_fact_tables: list[str] = Field(default_factory=list)


class MetricViewJoin(BaseModel):
    name: str
    source: str
    on: str
    type: str = "left"


class MetricViewDimension(BaseModel):
    name: str
    expr: str


class MetricViewMeasure(BaseModel):
    name: str
    expr: str


class MetricViewExcludedMeasure(BaseModel):
    name: str
    reason: str


class MetricViewSpec(BaseModel):
    """A provisional Unity Catalog Metric View YAML spec for one candidate
    fact table (backend/app/recommendations/metric_view_yaml.py), adapted
    from the pbi-unified skill's build_view.py. `source`/join `source`
    values are placeholders (Power BI table names, snake_cased) rather than
    real Unity Catalog three-part names — see `source_note`."""

    fact_table: str
    status: Status = Status.INFERRED
    version: str = "1.1"
    source: str
    source_note: str
    joins: list[MetricViewJoin] = Field(default_factory=list)
    dimensions: list[MetricViewDimension] = Field(default_factory=list)
    measures: list[MetricViewMeasure] = Field(default_factory=list)
    excluded_measures: list[MetricViewExcludedMeasure] = Field(default_factory=list)


class WrapperViewMeasure(BaseModel):
    name: str
    pattern: str
    sub_type: str
    base_measure: Optional[str] = None
    sql_column: str


class WrapperViewSkippedMeasure(BaseModel):
    name: str
    pattern: Optional[str] = None
    reason: str


class WrapperViewSpec(BaseModel):
    """A companion wrapper view (window functions / LAG / RANK — things a
    Metric View measure expr cannot contain) for one candidate fact table
    (backend/app/recommendations/wrapper_views.py), adapted from the
    pbi-unified skill's build_wrapper.py."""

    fact_table: str
    status: Status = Status.INFERRED
    date_dimension: Optional[str] = None
    group_by: list[str] = Field(default_factory=list)
    wrapped_measures: list[WrapperViewMeasure] = Field(default_factory=list)
    skipped_measures: list[WrapperViewSkippedMeasure] = Field(default_factory=list)
    sql: str


class SqlTranslationItem(BaseModel):
    """One measure's DAX -> Databricks SQL translation
    (backend/app/parsers/dax/sql_translator.py), adapted from the
    pbi-unified skill's translate.py Tier-1/Tier-2 stages."""

    measure_name: str
    table_name: str
    original_dax: str
    translated_sql: str
    status: str  # auto | auto_spot_check | needs_review | manual_port | unsupported
    complexity_category: str
    complexity_score: int
    notes: list[str] = Field(default_factory=list)


class MigrationGap(BaseModel):
    id: str
    object_ref: str
    missing_information: str
    why_it_matters: str
    migration_impact: str
    recommended_action: str
    status: Status = Status.REQUIRES_INPUT


class LineageNode(BaseModel):
    id: str
    node_type: str  # SEMANTIC_MODEL | TABLE | COLUMN | MEASURE
    ref_id: str
    label: str


class LineageEdge(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    edge_type: str  # MEASURE_TO_MEASURE | MEASURE_TO_COLUMN | COLUMN_TO_TABLE | TABLE_TO_TABLE


class ProjectData(BaseModel):
    """Everything canonical for one project — the unit persisted to storage."""

    project: Project
    semantic_models: list[PowerBISemanticModel] = Field(default_factory=list)
    gaps: list[MigrationGap] = Field(default_factory=list)


# --- Reporting / migration-plan shapes (backend/app/reporting, backend/app/migration). ---
# These are derived/templated from the canonical model above, not extracted from source
# metadata directly, so most instances carry status=REQUIRES_INPUT until the ingestion
# adapters that would confirm them (Teradata, Databricks, SQL/M parsing) exist.

class ReportSection(BaseModel):
    key: str
    title: str
    status: Status
    summary: str
    details: list[str] = Field(default_factory=list)


class AssessmentReport(BaseModel):
    project_name: str
    generated_at: datetime = Field(default_factory=utcnow)
    executive_summary: dict
    sections: list[ReportSection]


class MigrationPhase(BaseModel):
    key: str
    name: str
    status: Status
    tasks: list[str]
    blocked_reason: Optional[str] = None
