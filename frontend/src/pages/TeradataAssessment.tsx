import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PageHeader } from '../components/layout/PageHeader'
import { IconTeradata } from '../components/icons/Icons'
import { EmptyState } from '../components/ui/EmptyState'
import { MetricRow, SectionCard } from '../components/ui/SectionCard'
import { SkeletonStack } from '../components/ui/Skeleton'
import { useProject } from '../state/ProjectContext'
import type { Dashboard } from '../types/canonical'
import { NoProjectSelected } from './NoProjectSelected'

export function TeradataAssessment() {
  const { projectId, refreshKey } = useProject()
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    setData(null)
    api.getDashboard(projectId).then(setData).catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>
  if (!data) return <SkeletonStack rows={5} />

  const total = data.teradata_views + data.teradata_base_tables

  return (
    <div className="page">
      <PageHeader title="Teradata Assessment" subtitle="Views, base tables, and dependency resolution." />

      <SectionCard title="Teradata Objects">
        <MetricRow label="Views" value={data.teradata_views} />
        <MetricRow label="Base Tables" value={data.teradata_base_tables} />
        <MetricRow label="Referenced Objects" value={<span className="muted">Not yet available</span>} />
        <MetricRow label="Unresolved Objects" value={<span className="muted">Not yet available</span>} />
      </SectionCard>

      {total === 0 && (
        <EmptyState
          icon={<IconTeradata width={22} height={22} />}
          title="Teradata discovery not completed"
          body="No Teradata SQL, DDL, or object export has been ingested for this project yet. Once Teradata metadata is supplied, this page will show discovered views, base tables, and recursively resolved dependencies."
        />
      )}
    </div>
  )
}
