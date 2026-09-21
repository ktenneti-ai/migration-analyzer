import { IconMoon, IconRefresh, IconSun } from '../icons/Icons'
import { useProject } from '../../state/ProjectContext'
import { useTheme } from '../../state/ThemeContext'

export function TopHeader() {
  const { project, refresh } = useProject()
  const { theme, toggleTheme } = useTheme()

  const analyzed = (project?.source_artifacts.length ?? 0) > 0
  const lastArtifact = project?.source_artifacts
    .slice()
    .sort((a, b) => new Date(b.uploaded_at).getTime() - new Date(a.uploaded_at).getTime())[0]

  return (
    <header className="top-header">
      <div className="top-header__title">
        <strong>Migration Assessment</strong>
        <span>{project ? project.name : 'No project selected'}</span>
      </div>
      <div className="top-header__meta">
        {project && (
          <>
            <div className="top-header__stat">
              <span className="top-header__stat-label">Status</span>
              <span className="top-header__stat-value">{analyzed ? 'Analyzed' : 'Not started'}</span>
            </div>
            <div className="top-header__stat">
              <span className="top-header__stat-label">Last analyzed</span>
              <span className="top-header__stat-value">
                {lastArtifact ? new Date(lastArtifact.uploaded_at).toLocaleString() : '—'}
              </span>
            </div>
          </>
        )}
        <button
          type="button"
          className="icon-btn"
          onClick={refresh}
          aria-label="Refresh assessment data"
          title="Refresh assessment data"
        >
          <IconRefresh />
        </button>
        <button
          type="button"
          className="icon-btn"
          onClick={toggleTheme}
          aria-label="Toggle color theme"
          title="Toggle color theme"
        >
          {theme === 'dark' ? <IconSun /> : <IconMoon />}
        </button>
      </div>
    </header>
  )
}
