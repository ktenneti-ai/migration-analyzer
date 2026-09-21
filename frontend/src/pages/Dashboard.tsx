import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { AssessmentSummary } from '../components/ui/AssessmentSummary'
import { ComplexityBar } from '../components/ui/ComplexityBadge'
import { MigrationFlow, type FlowStage } from '../components/ui/MigrationFlow'
import { ProgressIndicator, type StageInfo } from '../components/ui/MigrationStage'
import { SectionCard, MetricRow } from '../components/ui/SectionCard'
import { SkeletonStack } from '../components/ui/Skeleton'
import { PageHeader } from '../components/layout/PageHeader'
import { useProject } from '../state/ProjectContext'
import { gapObjectName, gapSource } from '../utils/gaps'
import type { Dashboard as DashboardData, MigrationGap, MigrationPhase } from '../types/canonical'
import { NoProjectSelected } from './NoProjectSelected'

function computeStages(data: DashboardData): StageInfo[] {
  const teradataTotal = data.teradata_views + data.teradata_base_tables + data.teradata_referenced_objects
  const databricksTotal = data.bronze_tables + data.silver_tables + data.gold_facts + data.gold_dimensions

  return [
    {
      key: 'powerbi',
      label: 'Power BI Analysis',
      status: data.tables === 0 ? 'not_started' : data.migration_gaps > 0 ? 'warning' : 'complete',
      note:
        data.tables === 0
          ? 'No Power BI metadata ingested yet.'
          : data.migration_gaps > 0
            ? `${data.migration_gaps} unresolved reference(s) found.`
            : 'Power BI metadata extracted with no unresolved references.',
    },
    {
      key: 'teradata',
      label: 'Teradata Discovery',
      status: teradataTotal === 0 ? 'not_started' : 'complete',
      note: teradataTotal === 0 ? 'Teradata discovery not completed.' : 'Teradata objects discovered.',
    },
    {
      key: 'lineage',
      label: 'Lineage Mapping',
      status: data.tables === 0 ? 'not_started' : 'complete',
      note: data.tables === 0 ? 'Nothing to map yet.' : 'Power BI lineage graph built.',
    },
    {
      key: 'databricks',
      label: 'Databricks Design',
      status: databricksTotal > 0 ? 'complete' : teradataTotal > 0 ? 'in_progress' : 'not_started',
      note:
        databricksTotal > 0
          ? 'Bronze/Silver/Gold design available.'
          : teradataTotal > 0
            ? 'Teradata discovered; Databricks design not yet generated.'
            : 'Requires Teradata discovery first.',
    },
    {
      key: 'validation',
      label: 'Validation',
      status: 'not_started',
      note: 'Validation framework not yet implemented.',
    },
  ]
}

function buildFlow(data: DashboardData): FlowStage[] {
  const gold = data.gold_facts + data.gold_dimensions
  return [
    { key: 'powerbi-source', name: 'Power BI', count: data.tables },
    {
      key: 'teradata',
      name: 'Teradata',
      count:
        data.teradata_base_tables > 0
          ? data.teradata_base_tables
          : data.teradata_referenced_objects > 0
            ? data.teradata_referenced_objects
            : null,
      note:
        data.teradata_base_tables > 0
          ? undefined
          : data.teradata_referenced_objects > 0
            ? 'Referenced via Power BI import queries — no Teradata SQL/DDL export ingested yet'
            : 'Teradata discovery not completed',
    },
    {
      key: 'bronze',
      name: 'Bronze',
      count: data.bronze_tables > 0 ? data.bronze_tables : null,
      note: 'Awaiting Teradata discovery',
    },
    {
      key: 'silver',
      name: 'Silver',
      count: data.silver_tables > 0 ? data.silver_tables : null,
      note: 'Awaiting Bronze design',
    },
    {
      key: 'gold',
      name: 'Gold',
      count: gold > 0 ? gold : null,
      note: 'Awaiting Silver design',
    },
    {
      key: 'analytics',
      name: 'Power BI / Analytics',
      count: gold > 0 ? data.reports : null,
      note: 'Awaiting Gold-backed semantic model',
    },
  ]
}

export function Dashboard() {
  const { projectId, refreshKey } = useProject()
  const [data, setData] = useState<DashboardData | null>(null)
  const [gaps, setGaps] = useState<MigrationGap[]>([])
  const [plan, setPlan] = useState<MigrationPhase[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    setData(null)
    Promise.all([api.getDashboard(projectId), api.getGaps(projectId), api.getMigrationPlan(projectId)])
      .then(([d, g, p]) => {
        setData(d)
        setGaps(g)
        setPlan(p)
      })
      .catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>
  if (!data) {
    return (
      <div className="page">
        <PageHeader title="Migration Assessment" subtitle="Power BI → Teradata → Databricks" />
        <SkeletonStack rows={6} />
      </div>
    )
  }

  const readiness = plan.length
    ? Math.round((plan.filter((p) => p.status === 'CONFIRMED').length / plan.length) * 100)
    : 0

  return (
    <div className="page">
      <PageHeader title="Migration Assessment" subtitle="Power BI → Teradata → Databricks" />

      <ProgressIndicator stages={computeStages(data)} />

      <AssessmentSummary data={data} />

      <div className="section-label">Source & target systems</div>
      <div className="kpi-grid">
        <SectionCard title="Power BI Assessment">
          <MetricRow label="Semantic Models" value={data.semantic_models} />
          <MetricRow label="Tables" value={data.tables} />
          <MetricRow label="Columns" value={data.columns} />
          <MetricRow label="Measures" value={data.measures} />
          <MetricRow label="Relationships" value={data.relationships} />
        </SectionCard>

        <SectionCard title="Teradata Assessment">
          <MetricRow label="Views" value={data.teradata_views} />
          <MetricRow label="Base Tables" value={data.teradata_base_tables} />
          <MetricRow label="Referenced Objects" value={data.teradata_referenced_objects} />
          <MetricRow label="Unresolved Objects" value={data.teradata_unresolved_objects} />
        </SectionCard>

        <SectionCard title="Databricks Target">
          <MetricRow label="Bronze Tables" value={data.bronze_tables} />
          <MetricRow label="Silver Tables" value={data.silver_tables} />
          <MetricRow label="Gold Facts" value={data.gold_facts} />
          <MetricRow label="Gold Dimensions" value={data.gold_dimensions} />
        </SectionCard>
      </div>

      <div className="section-label">Migration readiness</div>
      <div className="kpi-grid">
        <SectionCard title="Overall Readiness">
          <div className="kpi-card__value" style={{ fontSize: 30 }}>
            {readiness}%
          </div>
          <p className="muted">{plan.filter((p) => p.status === 'CONFIRMED').length} of {plan.length} migration phases confirmed</p>
        </SectionCard>
        <SectionCard title="Migration Gaps">
          <div className="kpi-card__value" style={{ fontSize: 30 }}>
            {data.migration_gaps}
          </div>
          <p className="muted">
            <Link to="/gaps">View all gaps →</Link>
          </p>
        </SectionCard>
        <SectionCard title="Complexity Distribution">
          <ComplexityBar low={data.complexity.LOW} medium={data.complexity.MEDIUM} high={data.complexity.HIGH} />
        </SectionCard>
      </div>

      <div className="section-label">Migration flow</div>
      <MigrationFlow stages={buildFlow(data)} />

      <div className="section-label">Migration gaps requiring attention</div>
      {gaps.length === 0 ? (
        <p className="empty-state">No migration gaps identified yet.</p>
      ) : (
        <div className="table-card">
          <table>
            <thead>
              <tr>
                <th>Object</th>
                <th>Source</th>
                <th>Issue</th>
                <th>Recommended Action</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {gaps.slice(0, 5).map((gap) => (
                <tr key={gap.id}>
                  <td>{gapObjectName(gap)}</td>
                  <td>{gapSource(gap)}</td>
                  <td className="gap-issue">{gap.missing_information}</td>
                  <td>{gap.recommended_action}</td>
                  <td>{gap.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {gaps.length > 5 && (
        <p className="muted" style={{ marginTop: 8 }}>
          <Link to="/gaps">View all {gaps.length} gaps →</Link>
        </p>
      )}
    </div>
  )
}
