import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { IconDatabricks } from '../components/icons/Icons'
import { PageHeader } from '../components/layout/PageHeader'
import { StatusBadge } from '../components/tables/InventoryTable'
import { EmptyState } from '../components/ui/EmptyState'
import { SectionCard } from '../components/ui/SectionCard'
import { SkeletonStack } from '../components/ui/Skeleton'
import { useProject } from '../state/ProjectContext'
import type { GoldResponse } from '../types/canonical'
import { NoProjectSelected } from './NoProjectSelected'

export function MetricView() {
  const { projectId, refreshKey } = useProject()
  const [data, setData] = useState<GoldResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    setData(null)
    api.getGold(projectId).then(setData).catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>

  return (
    <div className="page">
      <PageHeader
        title="Databricks Metric View"
        subtitle="Bronze / Silver / Gold design — facts, dimensions, bridges, aggregates."
      />
      {!data ? (
        <SkeletonStack rows={4} />
      ) : data.pending ? (
        <EmptyState
          icon={<IconDatabricks width={22} height={22} />}
          title="Gold-layer design not yet available"
          body={data.reason}
        />
      ) : (
        <>
          <p className="muted" style={{ marginBottom: 16 }}>
            {data.reason}
          </p>

          <div className="section-label">Candidate fact tables</div>
          {data.facts.map((fact) => (
            <SectionCard
              key={fact.table_name}
              title={fact.table_name}
              action={<StatusBadge status={fact.status} />}
            >
              <p className="muted" style={{ marginBottom: 8 }}>
                {fact.measures.length} measure(s): {fact.measures.join(', ')}
              </p>
              <ul className="report-section__details" style={{ marginBottom: 8 }}>
                {fact.evidence.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
              <p className="status-msg status-msg--error">{fact.grain}</p>
            </SectionCard>
          ))}

          <div className="section-label">Candidate dimension tables</div>
          {data.dimensions.length === 0 ? (
            <p className="empty-state">No candidate dimensions found (no relationships to a candidate fact table).</p>
          ) : (
            <div className="kpi-grid">
              {data.dimensions.map((dim) => (
                <SectionCard key={dim.table_name} title={dim.table_name} action={<StatusBadge status={dim.status} />}>
                  <p className="muted" style={{ marginBottom: 8 }}>
                    Related to: {dim.related_fact_tables.join(', ')}
                  </p>
                  <ul className="report-section__details">
                    {dim.evidence.map((e) => (
                      <li key={e}>{e}</li>
                    ))}
                  </ul>
                </SectionCard>
              ))}
            </div>
          )}

          <div className="section-label">Metric View YAML (provisional)</div>
          {data.metric_views.length === 0 ? (
            <p className="empty-state">
              No candidate fact table has a usable (auto/auto_spot_check) measure yet, so no Metric
              View spec could be generated.
            </p>
          ) : (
            data.metric_views.map((spec) => (
              <SectionCard
                key={spec.fact_table}
                title={`metric_view_${spec.fact_table}.yaml`}
                action={
                  <a
                    className="button-link"
                    href={api.getMetricViewExportUrl(projectId, spec.fact_table)}
                  >
                    Download YAML
                  </a>
                }
              >
                <p className="muted" style={{ marginBottom: 8 }}>
                  {spec.measures.length} measure(s) included · {spec.joins.length} join(s) ·{' '}
                  {spec.dimensions.length} dimension(s) · {spec.source_note}
                </p>
                <pre className="yaml-block">{spec.yaml}</pre>
                {spec.excluded_measures.length > 0 && (
                  <>
                    <p className="muted" style={{ marginTop: 12, marginBottom: 4 }}>
                      Excluded measures:
                    </p>
                    <ul className="report-section__details">
                      {spec.excluded_measures.map((e) => (
                        <li key={e.name}>
                          {e.name}: {e.reason}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </SectionCard>
            ))
          )}

          <div className="section-label">Wrapper views (window functions / LAG / RANK)</div>
          {data.wrapper_views.length === 0 ? (
            <p className="empty-state">
              No measures need a wrapper view yet — either every measure fits inside its metric
              view, or none of the excluded measures matched a recognized wrapper pattern.
            </p>
          ) : (
            data.wrapper_views.map((spec) => (
              <SectionCard
                key={spec.fact_table}
                title={`wrapper_view_${spec.fact_table}.sql`}
                action={
                  spec.wrapped_measures.length > 0 ? (
                    <a className="button-link" href={api.getWrapperViewExportUrl(projectId, spec.fact_table)}>
                      Download SQL
                    </a>
                  ) : undefined
                }
              >
                <p className="muted" style={{ marginBottom: 8 }}>
                  {spec.wrapped_measures.length} measure(s) wrapped
                  {spec.date_dimension ? ` · date dimension: ${spec.date_dimension}` : ''}
                </p>
                {spec.wrapped_measures.length > 0 && <pre className="yaml-block">{spec.sql}</pre>}
                {spec.skipped_measures.length > 0 && (
                  <>
                    <p className="muted" style={{ marginTop: 12, marginBottom: 4 }}>
                      Skipped measures:
                    </p>
                    <ul className="report-section__details">
                      {spec.skipped_measures.map((s) => (
                        <li key={s.name}>
                          {s.name} ({s.pattern}): {s.reason}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </SectionCard>
            ))
          )}

          <div className="section-label">Bridges & aggregates</div>
          <p className="empty-state">
            Not yet inferable from Power BI metadata alone — requires Teradata source data and the
            Databricks migration engine.
          </p>
        </>
      )}
    </div>
  )
}
