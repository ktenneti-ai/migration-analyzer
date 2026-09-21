import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { StatusBadge } from '../components/tables/InventoryTable'
import { SkeletonStack } from '../components/ui/Skeleton'
import { useProject } from '../state/ProjectContext'
import type { AssessmentReport as AssessmentReportData } from '../types/canonical'
import { NoProjectSelected } from './NoProjectSelected'

export function AssessmentReport() {
  const { projectId, refreshKey } = useProject()
  const [report, setReport] = useState<AssessmentReportData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    setReport(null)
    api.getReport(projectId).then(setReport).catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>
  if (!report) {
    return (
      <div className="page">
        <h1>Migration Assessment Report</h1>
        <SkeletonStack rows={6} />
      </div>
    )
  }

  const summary = report.executive_summary

  return (
    <div className="page">
      <div className="report-header">
        <div>
          <h1>Migration Assessment Report</h1>
          <p className="muted">
            {report.project_name} — generated {new Date(report.generated_at).toLocaleString()}
          </p>
        </div>
        <div className="report-header__actions">
          <a className="button-link" href={api.getReportExportUrl(projectId, 'pdf')}>
            Export PDF
          </a>
          <a className="button-link" href={api.getReportExportUrl(projectId, 'docx')}>
            Export Word
          </a>
        </div>
      </div>

      <section className="card">
        <h2>Executive Summary</h2>
        <div className="stat-grid">
          <div className="stat-tile">
            <div className="stat-tile__value">{summary.semantic_models}</div>
            <div className="stat-tile__label">Semantic Models</div>
          </div>
          <div className="stat-tile">
            <div className="stat-tile__value">{summary.tables}</div>
            <div className="stat-tile__label">Tables</div>
          </div>
          <div className="stat-tile">
            <div className="stat-tile__value">{summary.measures}</div>
            <div className="stat-tile__label">Measures</div>
          </div>
          <div className="stat-tile">
            <div className="stat-tile__value">{summary.relationships}</div>
            <div className="stat-tile__label">Relationships</div>
          </div>
          <div className="stat-tile">
            <div className="stat-tile__value">{summary.migration_gaps}</div>
            <div className="stat-tile__label">Migration Gaps</div>
          </div>
        </div>
      </section>

      {report.sections.map((section) => (
        <section
          className={`card report-section report-section--${section.status.toLowerCase()}`}
          key={section.key}
        >
          <div className="report-section__header">
            <h2>{section.title}</h2>
            <StatusBadge status={section.status} />
          </div>
          <p>{section.summary}</p>
          {section.details.length > 0 && (
            <ul className="report-section__details">
              {section.details.map((d, i) => (
                <li key={i}>{d}</li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  )
}
