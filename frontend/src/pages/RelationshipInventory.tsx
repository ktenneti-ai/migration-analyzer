import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PageHeader } from '../components/layout/PageHeader'
import { PowerBITabs } from '../components/layout/PowerBITabs'
import { InventoryTable, StatusBadge } from '../components/tables/InventoryTable'
import { SkeletonStack } from '../components/ui/Skeleton'
import { useProject } from '../state/ProjectContext'
import type { RelationshipRow } from '../types/canonical'
import { NoProjectSelected } from './NoProjectSelected'

export function RelationshipInventory() {
  const { projectId, refreshKey } = useProject()
  const [rows, setRows] = useState<RelationshipRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    setRows(null)
    api.getRelationships(projectId).then(setRows).catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>

  return (
    <div className="page">
      <PageHeader title="Relationship Inventory" subtitle="Relationships between Power BI tables." />
      <PowerBITabs />
      {!rows ? (
        <SkeletonStack rows={4} />
      ) : (
        <InventoryTable
          rows={rows}
          emptyMessage="No relationships extracted yet."
          getRowKey={(r, i) => `${r.from_table}.${r.from_column}-${r.to_table}.${r.to_column}-${i}`}
          columns={[
            { header: 'From Table', render: (r) => r.from_table },
            { header: 'From Column', render: (r) => r.from_column },
            { header: 'To Table', render: (r) => r.to_table },
            { header: 'To Column', render: (r) => r.to_column },
            { header: 'Cardinality', render: (r) => r.cardinality },
            { header: 'Direction', render: (r) => r.cross_filter_direction },
            { header: 'Active', render: (r) => (r.is_active ? 'Yes' : 'No') },
            { header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
          ]}
        />
      )}
    </div>
  )
}
