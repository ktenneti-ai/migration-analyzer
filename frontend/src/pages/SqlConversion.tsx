import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { IconSql } from '../components/icons/Icons'
import { PageHeader } from '../components/layout/PageHeader'
import { InventoryTable, StatusBadge } from '../components/tables/InventoryTable'
import { EmptyState } from '../components/ui/EmptyState'
import { SkeletonStack } from '../components/ui/Skeleton'
import { useProject } from '../state/ProjectContext'
import type { SqlConversionResponse } from '../types/canonical'
import { sqlStatusToBadgeStatus } from '../utils/sqlStatus'
import { NoProjectSelected } from './NoProjectSelected'

export function SqlConversion() {
  const { projectId, refreshKey } = useProject()
  const [data, setData] = useState<SqlConversionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    setData(null)
    api.getSqlConversion(projectId).then(setData).catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>

  return (
    <div className="page">
      <PageHeader
        title="SQL Conversion Report"
        subtitle="Power BI DAX measures translated toward Databricks SQL, gated by complexity classification."
      />
      {!data ? (
        <SkeletonStack rows={4} />
      ) : data.pending ? (
        <EmptyState icon={<IconSql width={22} height={22} />} title="SQL conversion not yet available" body={data.reason} />
      ) : (
        <>
          <p className="muted" style={{ marginBottom: 16 }}>
            {data.reason}
          </p>
          <InventoryTable
            rows={data.items}
            emptyMessage="No measures to translate yet."
            getRowKey={(i) => `${i.table_name}.${i.measure_name}`}
            columns={[
              { header: 'Measure', render: (i) => i.measure_name },
              { header: 'Table', render: (i) => i.table_name },
              { header: 'Original DAX', render: (i) => <code className="dax-expr">{i.original_dax}</code> },
              { header: 'Databricks SQL', render: (i) => <code className="dax-expr">{i.translated_sql}</code> },
              { header: 'Category', render: (i) => i.complexity_category },
              { header: 'Notes', render: (i) => i.notes.join('; ') || '—' },
              { header: 'Status', render: (i) => <StatusBadge status={sqlStatusToBadgeStatus(i.status)} /> },
            ]}
          />
        </>
      )}
    </div>
  )
}
