import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PageHeader } from '../components/layout/PageHeader'
import { InventoryTable, StatusBadge } from '../components/tables/InventoryTable'
import { SkeletonStack } from '../components/ui/Skeleton'
import { useProject } from '../state/ProjectContext'
import { gapObjectName, gapSource } from '../utils/gaps'
import type { MigrationGap } from '../types/canonical'
import { NoProjectSelected } from './NoProjectSelected'

export function GapsPage() {
  const { projectId, refreshKey } = useProject()
  const [gaps, setGaps] = useState<MigrationGap[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    setGaps(null)
    api.getGaps(projectId).then(setGaps).catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>

  return (
    <div className="page">
      <PageHeader
        title="Migration Gaps Requiring Attention"
        subtitle="Information the assessment could not determine from the metadata supplied so far."
      />
      {!gaps ? (
        <SkeletonStack rows={5} />
      ) : (
        <InventoryTable
          rows={gaps}
          emptyMessage="No migration gaps identified yet."
          getRowKey={(g) => g.id}
          columns={[
            {
              header: 'Severity',
              render: () => <span className="severity-badge severity-badge--unclassified">Not classified</span>,
            },
            { header: 'Object', render: (g) => gapObjectName(g) },
            { header: 'Source', render: (g) => gapSource(g) },
            { header: 'Issue', render: (g) => <span className="gap-issue">{g.missing_information}</span> },
            { header: 'Recommended Action', render: (g) => g.recommended_action },
            { header: 'Status', render: (g) => <StatusBadge status={g.status} /> },
          ]}
        />
      )}
    </div>
  )
}
