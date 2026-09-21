// Mirrors backend/app/metadata/models.py. Kept in one file, matching the
// backend's single canonical model, so every input format's data renders
// through the same shapes.

export type Status = 'CONFIRMED' | 'INFERRED' | 'REQUIRES_INPUT'

export interface Provenance {
  source_file: string
  source_type: string
  json_path?: string | null
  extracted_at: string
}

export interface SourceArtifact {
  id: string
  filename: string
  file_type: string
  uploaded_at: string
  raw_schema_summary?: string | null
  detected_schema: string
}

export interface Project {
  id: string
  name: string
  created_at: string
  source_artifacts: SourceArtifact[]
}

export interface TableRow {
  object_type: string
  name: string
  // Set only for Power BI's auto-generated date tables (GUID-suffixed
  // names) — a human-readable label derived from the column they were
  // built for. `name` is always the real underlying identifier.
  display_name: string | null
  parent: string
  source: string | null
  columns: number
  measures: number
  status: Status
}

export type ComplexityBand = 'AUTO' | 'AUTO_SPOT_CHECK' | 'NEEDS_REVIEW' | 'MANUAL_PORT' | 'UNSUPPORTED'

export interface MeasureRow {
  name: string
  table: string
  expression: string
  referenced_measures: string[]
  referenced_columns: string[]
  dependent_tables: string[]
  dependency_depth: number
  status: Status
  functions_used: string[]
  complexity_score: number
  complexity_band: ComplexityBand
  complexity_category: string
  complexity_reasons: string[]
}

export interface RelationshipRow {
  model: string
  from_table: string
  from_table_display: string | null
  from_column: string
  to_table: string
  to_table_display: string | null
  to_column: string
  cardinality: string
  cross_filter_direction: string
  is_active: boolean
  source: string
  status: Status
}

export interface MigrationGap {
  id: string
  object_ref: string
  missing_information: string
  why_it_matters: string
  migration_impact: string
  recommended_action: string
  status: Status
}

export interface Dashboard {
  reports: number
  semantic_models: number
  tables: number
  columns: number
  measures: number
  relationships: number
  teradata_views: number
  teradata_base_tables: number
  teradata_referenced_objects: number
  teradata_unresolved_objects: number
  bronze_tables: number
  silver_tables: number
  gold_facts: number
  gold_dimensions: number
  migration_gaps: number
  complexity: { LOW: number; MEDIUM: number; HIGH: number }
}

export interface LineageNode {
  id: string
  node_type: 'TERADATA_SOURCE' | 'SOURCE' | 'SEMANTIC_MODEL' | 'TABLE' | 'COLUMN' | 'MEASURE'
  ref_id: string
  label: string
  // True for nodes belonging to a Power BI Auto Date/Time table — hidden by
  // default in the Lineage Explorer, matching the Tables/Relationships tabs.
  is_system: boolean
  // Click-to-inspect detail — DAX expression, dependencies, data type, etc.
  // Shape varies by node_type; only fields the canonical model actually has
  // are present (see backend/app/graph/builder.py).
  detail: Record<string, unknown>
}

export interface LineageEdge {
  id: string
  source_node_id: string
  target_node_id: string
  edge_type: string
}

export interface LineageGraphData {
  nodes: LineageNode[]
  edges: LineageEdge[]
}

export interface ReportSection {
  key: string
  title: string
  status: Status
  summary: string
  details: string[]
}

export interface AssessmentReport {
  project_name: string
  generated_at: string
  executive_summary: Dashboard
  sections: ReportSection[]
}

export interface MigrationPhase {
  key: string
  name: string
  status: Status
  tasks: string[]
  blocked_reason: string | null
}

export interface PendingCollection {
  pending: boolean
  reason: string
}

export type SqlTranslationStatus = 'auto' | 'auto_spot_check' | 'needs_review' | 'manual_port' | 'unsupported'

export interface SqlTranslationItem {
  measure_name: string
  table_name: string
  original_dax: string
  translated_sql: string
  status: SqlTranslationStatus
  complexity_category: string
  complexity_score: number
  notes: string[]
}

export interface SqlConversionResponse extends PendingCollection {
  items: SqlTranslationItem[]
}

export interface GoldFactCandidate {
  table_name: string
  status: Status
  evidence: string[]
  measures: string[]
  grain: string
}

export interface GoldDimensionCandidate {
  table_name: string
  status: Status
  evidence: string[]
  related_fact_tables: string[]
}

export interface MetricViewJoin {
  name: string
  source: string
  on: string
  type: string
}

export interface MetricViewDimension {
  name: string
  expr: string
}

export interface MetricViewMeasure {
  name: string
  expr: string
}

export interface MetricViewExcludedMeasure {
  name: string
  reason: string
}

export interface MetricViewSpec {
  fact_table: string
  status: Status
  version: string
  source: string
  source_note: string
  joins: MetricViewJoin[]
  dimensions: MetricViewDimension[]
  measures: MetricViewMeasure[]
  excluded_measures: MetricViewExcludedMeasure[]
  yaml: string
}

export interface WrapperViewMeasure {
  name: string
  pattern: string
  sub_type: string
  base_measure: string | null
  sql_column: string
}

export interface WrapperViewSkippedMeasure {
  name: string
  pattern: string | null
  reason: string
}

export interface WrapperViewSpec {
  fact_table: string
  status: Status
  date_dimension: string | null
  group_by: string[]
  wrapped_measures: WrapperViewMeasure[]
  skipped_measures: WrapperViewSkippedMeasure[]
  sql: string
}

export interface GoldResponse extends PendingCollection {
  facts: GoldFactCandidate[]
  dimensions: GoldDimensionCandidate[]
  bridges: unknown[]
  aggregates: unknown[]
  metric_views: MetricViewSpec[]
  wrapper_views: WrapperViewSpec[]
}

export interface TeradataReferencedObject {
  model: string
  power_bi_table: string
  teradata_database: string | null
  teradata_schema: string | null
  teradata_object: string | null
  columns: number
  measures: number
  source_file: string
  status: Status
}

export interface TeradataUnresolvedTable {
  model: string
  power_bi_table: string
  columns: number
  measures: number
  source_file: string
  reason: string
}
