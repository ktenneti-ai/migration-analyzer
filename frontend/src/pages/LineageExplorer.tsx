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
  // Columns and measures are hidden by default — with hundreds of each, a
  // graph rendering every one is a wall of same-shaped nodes and edges that
  // drowns out the thing that actually matters here: which real tables
  // relate to which. Table-level lineage first; drill into detail on demand.
  const [showColumnsAndMeasures, setShowColumnsAndMeasures] = useState(false)

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
  const detailCount = data.nodes.filter((n) => n.node_type === 'COLUMN' || n.node_type === 'MEASURE').length

  const visibleData: LineageGraphData = (() => {
    let nodes = data.nodes
    let edges = data.edges
    if (!showSystemTables) {
      nodes = nodes.filter((n) => !n.is_system)
    }
    if (!showColumnsAndMeasures) {
      nodes = nodes.filter((n) => n.node_type !== 'COLUMN' && n.node_type !== 'MEASURE')
    }
    const visibleIds = new Set(nodes.map((n) => n.id))
    edges = edges.filter((e) => visibleIds.has(e.source_node_id) && visibleIds.has(e.target_node_id))
    return { nodes, edges }
  })()

  return (
    <div className="page page--full">
      <PageHeader
        title="Lineage Explorer"
        subtitle="Power BI stages only for now — Teradata and Databricks stages appear once that metadata is ingested."
        actions={
          <>
            {detailCount > 0 && (
              <label className="filter-toggle">
                <input
                  type="checkbox"
                  checked={showColumnsAndMeasures}
                  onChange={(e) => setShowColumnsAndMeasures(e.target.checked)}
                />
                Show {detailCount} column & measure node{detailCount === 1 ? '' : 's'}
              </label>
            )}
            {systemCount > 0 && (
              <label className="filter-toggle">
                <input
                  type="checkbox"
                  checked={showSystemTables}
                  onChange={(e) => setShowSystemTables(e.target.checked)}
                />
                Show {systemCount} Power BI system table{systemCount === 1 ? '' : 's'} (auto date/time)
              </label>
            )}
          </>
        }
      />
      <LineageGraph data={visibleData} />
    </div>
  )
}
