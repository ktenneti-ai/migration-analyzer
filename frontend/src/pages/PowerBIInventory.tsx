import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PageHeader } from '../components/layout/PageHeader'
import { PowerBITabs } from '../components/layout/PowerBITabs'
import { InventoryTable, StatusBadge } from '../components/tables/InventoryTable'
import { SkeletonStack } from '../components/ui/Skeleton'
import { useProject } from '../state/ProjectContext'
import type { TableRow } from '../types/canonical'
import { NoProjectSelected } from './NoProjectSelected'

export function PowerBIInventory() {
  const { projectId, refreshKey } = useProject()
  const [rows, setRows] = useState<TableRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    setRows(null)
    api.getTables(projectId).then(setRows).catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>

  return (
    <div className="page">
      <PageHeader title="Power BI Inventory" subtitle="Tables, measures, and relationships extracted from ingested semantic models." />
      <PowerBITabs />
      {!rows ? (
        <SkeletonStack rows={4} />
      ) : (
        <InventoryTable
          rows={rows}
          emptyMessage="No tables extracted yet. Upload a Power BI semantic-model JSON file from Projects."
          getRowKey={(r) => r.name}
          columns={[
            { header: 'Object Type', render: (r) => r.object_type },
            { header: 'Name', render: (r) => r.name },
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
