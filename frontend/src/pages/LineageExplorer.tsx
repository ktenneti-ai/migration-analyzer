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
  const [showSystemTables, setShowSystemTables] = useState(false)

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

  const systemCount = data.nodes.filter((n) => n.is_system && n.node_type === 'TABLE').length
  const visibleData: LineageGraphData = showSystemTables
    ? data
    : (() => {
        const visibleIds = new Set(data.nodes.filter((n) => !n.is_system).map((n) => n.id))
        return {
          nodes: data.nodes.filter((n) => !n.is_system),
          edges: data.edges.filter((e) => visibleIds.has(e.source_node_id) && visibleIds.has(e.target_node_id)),
        }
      })()

  return (
    <div className="page page--full">
      <PageHeader
        title="Lineage Explorer"
        subtitle="Power BI stages only for now — Teradata and Databricks stages appear once that metadata is ingested."
        actions={
          systemCount > 0 ? (
            <label className="filter-toggle">
              <input
                type="checkbox"
                checked={showSystemTables}
                onChange={(e) => setShowSystemTables(e.target.checked)}
              />
              Show {systemCount} Power BI system table{systemCount === 1 ? '' : 's'} (auto date/time)
            </label>
          ) : undefined
        }
      />
      <LineageGraph data={visibleData} />
    </div>
  )
}
