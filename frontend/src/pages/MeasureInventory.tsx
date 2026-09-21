import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PageHeader } from '../components/layout/PageHeader'
import { PowerBITabs } from '../components/layout/PowerBITabs'
import { InventoryTable, StatusBadge } from '../components/tables/InventoryTable'
import { ComplexityBadge } from '../components/ui/ComplexityBadge'
import { SkeletonStack } from '../components/ui/Skeleton'
import { Tooltip } from '../components/ui/Tooltip'
import { useProject } from '../state/ProjectContext'
import type { MeasureRow } from '../types/canonical'
import { bandToBucket } from '../utils/complexity'
import { NoProjectSelected } from './NoProjectSelected'

export function MeasureInventory() {
  const { projectId, refreshKey } = useProject()
  const [rows, setRows] = useState<MeasureRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    setRows(null)
    api.getMeasures(projectId).then(setRows).catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>

  return (
    <div className="page">
      <PageHeader title="Measure Inventory" subtitle="DAX measures and their resolved dependency chains." />
      <PowerBITabs />
      {!rows ? (
        <SkeletonStack rows={4} />
      ) : (
        <InventoryTable
          rows={rows}
          emptyMessage="No measures extracted yet."
          getRowKey={(r) => `${r.table}.${r.name}`}
          columns={[
            { header: 'Measure', render: (r) => r.name },
            { header: 'Table', render: (r) => r.table },
            { header: 'DAX', render: (r) => <code className="dax-expr">{r.expression}</code> },
            { header: 'Referenced Measures', render: (r) => r.referenced_measures.join(', ') || '—' },
            { header: 'Referenced Columns', render: (r) => r.referenced_columns.join(', ') || '—' },
            { header: 'Depth', render: (r) => r.dependency_depth },
            {
              header: 'Complexity',
              render: (r) => (
                <Tooltip
                  label={`Category ${r.complexity_category} · score ${r.complexity_score} · ${r.complexity_reasons[0] ?? 'no deductions'}`}
                >
                  <ComplexityBadge level={bandToBucket(r.complexity_band)} />
                </Tooltip>
              ),
            },
            { header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
          ]}
        />
      )}
    </div>
  )
}
