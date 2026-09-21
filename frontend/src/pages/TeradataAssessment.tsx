import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { IconTeradata } from '../components/icons/Icons'
import { PageHeader } from '../components/layout/PageHeader'
import { InventoryTable, StatusBadge } from '../components/tables/InventoryTable'
import { EmptyState } from '../components/ui/EmptyState'
import { MetricRow, SectionCard } from '../components/ui/SectionCard'
import { SkeletonStack } from '../components/ui/Skeleton'
import { useProject } from '../state/ProjectContext'
import type { Dashboard, TeradataReferencedObject, TeradataUnresolvedTable } from '../types/canonical'
import { NoProjectSelected } from './NoProjectSelected'

export function TeradataAssessment() {
  const { projectId, refreshKey } = useProject()
  const [data, setData] = useState<Dashboard | null>(null)
  const [referenced, setReferenced] = useState<TeradataReferencedObject[] | null>(null)
  const [unresolved, setUnresolved] = useState<TeradataUnresolvedTable[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    setData(null)
    setReferenced(null)
    setUnresolved(null)
    Promise.all([
      api.getDashboard(projectId),
      api.getTeradataReferencedObjects(projectId),
      api.getTeradataUnresolvedTables(projectId),
    ])
      .then(([d, r, u]) => {
        setData(d)
        setReferenced(r)
        setUnresolved(u)
      })
      .catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>
  if (!data || !referenced || !unresolved) return <SkeletonStack rows={5} />

  const nothingAtAll =
    data.teradata_views === 0 && data.teradata_base_tables === 0 && referenced.length === 0 && unresolved.length === 0

  return (
    <div className="page">
      <PageHeader
        title="Teradata Assessment"
        subtitle="Objects referenced from the Power BI model's own import queries, plus views and base tables once a Teradata SQL/DDL export is ingested."
      />

      <SectionCard title="Teradata Objects">
        <MetricRow label="Views" value={data.teradata_views} />
        <MetricRow label="Base Tables" value={data.teradata_base_tables} />
        <MetricRow label="Referenced Objects" value={referenced.length} />
        <MetricRow label="Unresolved Objects" value={unresolved.length} />
      </SectionCard>

      {nothingAtAll ? (
        <EmptyState
          icon={<IconTeradata width={22} height={22} />}
          title="Teradata discovery not completed"
          body="No Power BI table with a recognizable Teradata partition, and no Teradata SQL/DDL export, has been ingested for this project yet."
        />
      ) : (
        <>
          {data.teradata_views === 0 && data.teradata_base_tables === 0 && (
            <p className="muted" style={{ marginBottom: 16 }}>
              Views and base tables require a Teradata SQL/DDL export, which hasn't been ingested for this
              project. The objects below were identified from the Power BI model's own import queries instead.
            </p>
          )}

          <div className="section-label">Referenced Teradata objects</div>
          <InventoryTable
            rows={referenced}
            emptyMessage="No Power BI table names a recognizable Teradata source."
            getRowKey={(r) => r.power_bi_table}
            columns={[
              { header: 'Power BI Table', render: (r) => r.power_bi_table },
              { header: 'Database', render: (r) => r.teradata_database ?? '—' },
              { header: 'Schema', render: (r) => r.teradata_schema ?? '—' },
              { header: 'Teradata Object', render: (r) => r.teradata_object ?? '—' },
              { header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
            ]}
          />

          <div className="section-label">Power BI tables without a recognized Teradata source</div>
          <InventoryTable
            rows={unresolved}
            emptyMessage="Every Power BI table resolved to a Teradata source."
            getRowKey={(r) => r.power_bi_table}
            columns={[
              { header: 'Power BI Table', render: (r) => r.power_bi_table },
              { header: 'Reason', render: (r) => r.reason },
            ]}
          />
        </>
      )}
    </div>
  )
}
