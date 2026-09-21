import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PageHeader } from '../components/layout/PageHeader'
import { PowerBITabs } from '../components/layout/PowerBITabs'
import { InventoryTable, StatusBadge } from '../components/tables/InventoryTable'
import { SkeletonStack } from '../components/ui/Skeleton'
import { TableName } from '../components/ui/TableName'
import { useProject } from '../state/ProjectContext'
import type { RelationshipRow } from '../types/canonical'
import { NoProjectSelected } from './NoProjectSelected'

export function RelationshipInventory() {
  const { projectId, refreshKey } = useProject()
  const [rows, setRows] = useState<RelationshipRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showSystemTables, setShowSystemTables] = useState(false)

  useEffect(() => {
    if (!projectId) return
    setRows(null)
    api.getRelationships(projectId).then(setRows).catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>

  // A relationship "involves a system table" whenever either side has a
  // display_name — only ever set for Power BI's Auto Date/Time tables (see
  // PowerBIInventory.tsx). Hidden by default so the count here matches the
  // Dashboard's relationship count.
  const isSystemRelationship = (r: RelationshipRow) => Boolean(r.from_table_display || r.to_table_display)
  const systemCount = rows?.filter(isSystemRelationship).length ?? 0
  const visibleRows = rows && !showSystemTables ? rows.filter((r) => !isSystemRelationship(r)) : rows

  return (
    <div className="page page--full">
      <PageHeader
        title="Relationship Inventory"
        subtitle="Relationships between Power BI tables."
        actions={
          systemCount > 0 ? (
            <label className="filter-toggle">
              <input
                type="checkbox"
                checked={showSystemTables}
                onChange={(e) => setShowSystemTables(e.target.checked)}
              />
              Show {systemCount} relationship{systemCount === 1 ? '' : 's'} to Power BI system tables
            </label>
          ) : undefined
        }
      />
      <PowerBITabs />
      {!rows ? (
        <SkeletonStack rows={4} />
      ) : (
        <InventoryTable
          rows={visibleRows ?? []}
          emptyMessage="No relationships extracted yet."
          getRowKey={(r, i) => `${r.from_table}.${r.from_column}-${r.to_table}.${r.to_column}-${i}`}
          columns={[
            { header: 'Model', render: (r) => r.model },
            { header: 'From Table', render: (r) => <TableName name={r.from_table} displayName={r.from_table_display} /> },
            { header: 'From Column', render: (r) => r.from_column },
            { header: 'To Table', render: (r) => <TableName name={r.to_table} displayName={r.to_table_display} /> },
            { header: 'To Column', render: (r) => r.to_column },
            { header: 'Cardinality', render: (r) => r.cardinality },
            { header: 'Direction', render: (r) => r.cross_filter_direction },
            { header: 'Active', render: (r) => (r.is_active ? 'Yes' : 'No') },
            { header: 'Source', render: (r) => r.source },
            { header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
          ]}
        />
      )}
    </div>
  )
}
