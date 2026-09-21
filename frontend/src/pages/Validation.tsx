import { PageHeader } from '../components/layout/PageHeader'
import { IconValidation } from '../components/icons/Icons'
import { EmptyState } from '../components/ui/EmptyState'
import { useProject } from '../state/ProjectContext'
import { NoProjectSelected } from './NoProjectSelected'

export function Validation() {
  const { projectId } = useProject()
  if (!projectId) return <NoProjectSelected />

  return (
    <div className="page">
      <PageHeader
        title="Validation"
        subtitle="Source-vs-target reconciliation for row counts, aggregates, keys, and measures."
      />
      <EmptyState
        icon={<IconValidation width={22} height={22} />}
        title="Validation framework not yet implemented"
        body="Validation compares Teradata and Databricks results once both exist — row counts, aggregate reconciliation, key checks, and Power BI measure comparisons. This requires Teradata ingestion and a deployed Databricks target, neither of which exists for this project yet."
      />
    </div>
  )
}
