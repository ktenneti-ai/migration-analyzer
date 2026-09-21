import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PageHeader } from '../components/layout/PageHeader'
import { LineageGraph } from '../components/lineage/LineageGraph'
import { SkeletonStack } from '../components/ui/Skeleton'
import { useProject } from '../state/ProjectContext'
import type { LineageGraphData } from '../types/canonical'
import { NoProjectSelected } from './NoProjectSelected'

export function LineageExplorer() {
  const { projectId, refreshKey } = useProject()
  const [data, setData] = useState<LineageGraphData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    setData(null)
    api.getLineage(projectId).then(setData).catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>
  if (!data) {
    return (
      <div className="page">
        <PageHeader title="Lineage Explorer" />
        <SkeletonStack rows={6} />
      </div>
    )
  }
  if (data.nodes.length === 0) {
    return (
      <div className="page">
        <PageHeader title="Lineage Explorer" />
        <p className="empty-state">No lineage yet — upload a Power BI semantic-model JSON file first.</p>
      </div>
    )
  }

  return (
    <div className="page page--full">
      <PageHeader
        title="Lineage Explorer"
        subtitle="Power BI stages only for now — Teradata and Databricks stages appear once that metadata is ingested."
      />
      <LineageGraph data={data} />
    </div>
  )
}
