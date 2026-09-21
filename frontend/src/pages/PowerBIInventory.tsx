import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PageHeader } from '../components/layout/PageHeader'
import { PowerBITabs } from '../components/layout/PowerBITabs'
import { InventoryTable, StatusBadge } from '../components/tables/InventoryTable'
import { SkeletonStack } from '../components/ui/Skeleton'
import { TableName } from '../components/ui/TableName'
import { useProject } from '../state/ProjectContext'
import type { TableRow } from '../types/canonical'
import { NoProjectSelected } from './NoProjectSelected'

export function PowerBIInventory() {
  const { projectId, refreshKey } = useProject()
  const [rows, setRows] = useState<TableRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showSystemTables, setShowSystemTables] = useState(false)

  useEffect(() => {
    if (!projectId) return
    setRows(null)
    api.getTables(projectId).then(setRows).catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>

  // display_name is only ever set for Power BI's Auto Date/Time system
  // tables (see backend/app/ingestion/tmdl/tmdl_adapter.py) — Power BI
  // Desktop's own model view hides these, so they're hidden here by
  // default too, matching the Dashboard's counts.
  const systemCount = rows?.filter((r) => r.display_name).length ?? 0
  const visibleRows = rows && !showSystemTables ? rows.filter((r) => !r.display_name) : rows

  return (
    <div className="page">
      <PageHeader
        title="Power BI Inventory"
        subtitle="Tables, measures, and relationships extracted from ingested semantic models."
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
      <PowerBITabs />
      {!rows ? (
        <SkeletonStack rows={4} />
      ) : (
        <InventoryTable
          rows={visibleRows ?? []}
          emptyMessage="No tables extracted yet. Upload a Power BI semantic-model JSON file from Projects."
          getRowKey={(r) => r.name}
          columns={[
            { header: 'Object Type', render: (r) => r.object_type },
            { header: 'Name', render: (r) => <TableName name={r.name} displayName={r.display_name} /> },
            { header: 'Parent', render: (r) => r.parent },
            { header: 'Source', render: (r) => r.source ?? '—' },
            { header: 'Columns', render: (r) => r.columns },
            { header: 'Measures', render: (r) => r.measures },
            { header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
          ]}
        />
      )}
    </div>
  )
}
