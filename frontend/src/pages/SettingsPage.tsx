import { PageHeader } from '../components/layout/PageHeader'
import { MetricRow, SectionCard } from '../components/ui/SectionCard'
import { useProject } from '../state/ProjectContext'
import { useTheme } from '../state/ThemeContext'

export function SettingsPage() {
  const { project } = useProject()
  const { theme, toggleTheme } = useTheme()

  return (
    <div className="page">
      <PageHeader title="Settings" />

      <SectionCard
        title="Appearance"
        action={
          <button type="button" className="button--secondary button--sm" onClick={toggleTheme}>
            Switch to {theme === 'dark' ? 'light' : 'dark'}
          </button>
        }
      >
        <MetricRow label="Theme" value={theme === 'dark' ? 'Dark' : 'Light'} />
      </SectionCard>

      {project && (
        <SectionCard title="Current project">
          <MetricRow label="Name" value={project.name} />
          <MetricRow label="Project ID" value={<code className="dax-expr">{project.id}</code>} />
          <MetricRow label="Created" value={new Date(project.created_at).toLocaleString()} />
          <MetricRow label="Files ingested" value={project.source_artifacts.length} />
        </SectionCard>
      )}
    </div>
  )
}
