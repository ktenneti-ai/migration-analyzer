import { api } from '../api/client'
import { PageHeader } from '../components/layout/PageHeader'
import { IconExports } from '../components/icons/Icons'
import { EmptyState } from '../components/ui/EmptyState'
import { SectionCard } from '../components/ui/SectionCard'
import { useProject } from '../state/ProjectContext'
import { NoProjectSelected } from './NoProjectSelected'

export function Exports() {
  const { projectId } = useProject()
  if (!projectId) return <NoProjectSelected />

  return (
    <div className="page">
      <PageHeader title="Exports" subtitle="Download assessment artifacts for this project." />

      <SectionCard title="Assessment Report">
        <p className="muted" style={{ marginBottom: 12 }}>
          The full Migration Assessment Report, including every section's status and evidence.
        </p>
        <div style={{ display: 'flex', gap: 8 }}>
          <a className="button-link" href={api.getReportExportUrl(projectId, 'pdf')}>
            Download PDF
          </a>
          <a className="button-link" href={api.getReportExportUrl(projectId, 'docx')}>
            Download Word
          </a>
        </div>
      </SectionCard>

      <EmptyState
        icon={<IconExports width={22} height={22} />}
        title="Inventory exports not yet implemented"
        body="CSV/Excel export of the Power BI, Teradata, and gap inventories, and JSON export of lineage metadata, are planned but not yet built. The Assessment Report above is the only export available today."
      />
    </div>
  )
}
