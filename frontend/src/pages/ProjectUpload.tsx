import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import {
  IconDashboard,
  IconDatabricks,
  IconGaps,
  IconLineage,
  IconPowerBI,
  IconReport,
} from '../components/icons/Icons'
import { PageHeader } from '../components/layout/PageHeader'
import { useProject } from '../state/ProjectContext'
import type { Dashboard, Project } from '../types/canonical'

function defaultProjectNameFromFile(filename: string): string {
  const base = filename.replace(/\.(json|tmdl)$/i, '')
  const cleaned = base.replace(/[_-]+/g, ' ').trim()
  return cleaned || 'New Project'
}

export function ProjectUpload() {
  const { projectId, setProjectId, refresh: refreshShellData } = useProject()
  const [projects, setProjects] = useState<Project[]>([])
  const [newName, setNewName] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pendingFiles, setPendingFiles] = useState<File[] | null>(null)
  const [pendingName, setPendingName] = useState('')
  const [justIngested, setJustIngested] = useState<Dashboard | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const refreshList = () => api.listProjects().then(setProjects).catch((e) => setError(String(e)))

  useEffect(() => {
    refreshList()
  }, [])

  // Switching projects (or deleting one) invalidates whatever "next steps"
  // summary was showing for the previous project.
  useEffect(() => {
    setJustIngested(null)
  }, [projectId])

  const createProject = async () => {
    if (!newName.trim()) return
    const project = await api.createProject(newName.trim())
    setNewName('')
    await refreshList()
    setProjectId(project.id)
  }

  const doIngest = async (id: string, files: File[]) => {
    setError(null)
    setJustIngested(null)
    let anySucceeded = false
    for (const file of files) {
      try {
        const result = await api.ingestFile(id, file)
        anySucceeded = true
        setStatus(
          `${file.name}: detected ${result.detected_schema}, extracted ${result.tables_extracted} table(s), ${result.measures_extracted} measure(s), ${result.gaps_found} gap(s) found.`,
        )
      } catch (e) {
        setError(`${file.name}: ${String(e)}`)
      }
    }
    await refreshList()
    refreshShellData() // so the dashboard, header "last analyzed", etc. pick up the new data
    if (anySucceeded) {
      api.getDashboard(id).then(setJustIngested).catch(() => {})
    }
  }

  const uploadFiles = (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return
    const files = Array.from(fileList)
    if (!projectId) {
      // No project selected yet — ask what to call it before ingesting,
      // instead of just erroring and making the user start over.
      setPendingFiles(files)
      setPendingName(defaultProjectNameFromFile(files[0].name))
      return
    }
    doIngest(projectId, files)
  }

  const confirmPendingUpload = async () => {
    if (!pendingFiles || !pendingName.trim()) return
    const project = await api.createProject(pendingName.trim())
    await refreshList()
    setProjectId(project.id)
    const files = pendingFiles
    setPendingFiles(null)
    setPendingName('')
    await doIngest(project.id, files)
  }

  const cancelPendingUpload = () => {
    setPendingFiles(null)
    setPendingName('')
  }

  const deleteProject = async (p: Project) => {
    if (!window.confirm(`Delete project "${p.name}" and everything ingested into it? This cannot be undone.`)) {
      return
    }
    await api.deleteProject(p.id)
    if (projectId === p.id) setProjectId(null)
    await refreshList()
  }

  const clearAllProjects = async () => {
    if (!window.confirm(`Delete all ${projects.length} project(s)? This cannot be undone.`)) {
      return
    }
    await api.deleteAllProjects()
    setProjectId(null)
    await refreshList()
  }

  const currentProject = projects.find((p) => p.id === projectId) ?? null

  return (
    <div className="page">
      <PageHeader title="Projects" subtitle="Create a migration project and upload Power BI metadata to analyze." />

      <section className="card">
        <h2>Create a project</h2>
        <div className="form-row">
          <input
            type="text"
            placeholder="Project name (e.g. Finance Migration)"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && createProject()}
          />
          <button onClick={createProject}>Create</button>
        </div>
      </section>

      <section className="card">
        <div className="card__header">
          <h2>Select a project</h2>
          {projects.length > 0 && (
            <button className="button--secondary button--sm" onClick={clearAllProjects}>
              Clear all projects
            </button>
          )}
        </div>
        {projects.length === 0 ? (
          <p className="empty-state">No projects yet — create one above, or just drop a file below.</p>
        ) : (
          <ul className="project-list">
            {projects.map((p) => (
              <li key={p.id} className={p.id === projectId ? 'active' : ''}>
                <button className="project-list__name-btn" onClick={() => setProjectId(p.id)}>
                  {p.name}
                </button>
                <span className="project-list__meta">
                  <span className="muted">{p.source_artifacts.length} file(s) ingested</span>
                  <button
                    className="button--secondary button--sm"
                    onClick={() => deleteProject(p)}
                    aria-label={`Delete ${p.name}`}
                  >
                    Delete
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        className={`card upload-dropzone ${dragOver ? 'upload-dropzone--active' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragOver(false)
          uploadFiles(e.dataTransfer.files)
        }}
      >
        <h2>Upload metadata</h2>
        <p className="muted">
          {currentProject ? `Uploading into "${currentProject.name}".` : "No project selected — you'll be asked to name one."}
          {' '}Milestone 1 supports .json and .tmdl files.
        </p>

        {pendingFiles ? (
          <div className="pending-project-prompt">
            <label htmlFor="pending-project-name">
              Name this project to ingest {pendingFiles.length === 1 ? pendingFiles[0].name : `${pendingFiles.length} files`}:
            </label>
            <div className="form-row">
              <input
                id="pending-project-name"
                type="text"
                autoFocus
                value={pendingName}
                onChange={(e) => setPendingName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && confirmPendingUpload()}
              />
              <button onClick={confirmPendingUpload}>Create & Upload</button>
              <button className="button--secondary" onClick={cancelPendingUpload}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="upload-dropzone__target" onClick={() => fileInput.current?.click()}>
            Drag & drop JSON or TMDL files here, or click to browse.
          </div>
        )}

        <input
          ref={fileInput}
          type="file"
          accept=".json,.tmdl"
          multiple
          hidden
          onChange={(e) => uploadFiles(e.target.files)}
        />
        {status && <p className="status-msg status-msg--ok">{status}</p>}
        {error && <p className="status-msg status-msg--error">{error}</p>}
      </section>

      {justIngested && (
        <section className="card next-steps">
          <h2>Where to next?</h2>
          <p className="muted" style={{ marginBottom: 12 }}>
            {currentProject?.name ?? 'This project'} now has {justIngested.tables} table(s), {justIngested.measures}{' '}
            measure(s), and {justIngested.relationships} relationship(s). Here's where to find the analysis:
          </p>
          <div className="next-steps__grid">
            <Link to="/" className="next-steps__link">
              <IconDashboard width={18} height={18} />
              <span>
                <strong>Dashboard</strong>
                <small>Full assessment summary at a glance</small>
              </span>
            </Link>
            <Link to="/powerbi/tables" className="next-steps__link">
              <IconPowerBI width={18} height={18} />
              <span>
                <strong>Power BI Inventory</strong>
                <small>Browse extracted tables, measures & relationships</small>
              </span>
            </Link>
            <Link to="/lineage" className="next-steps__link">
              <IconLineage width={18} height={18} />
              <span>
                <strong>Lineage Explorer</strong>
                <small>Visualize measure & table dependencies</small>
              </span>
            </Link>
            <Link to="/gaps" className="next-steps__link">
              <IconGaps width={18} height={18} />
              <span>
                <strong>Migration Gaps</strong>
                <small>
                  {justIngested.migration_gaps > 0
                    ? `${justIngested.migration_gaps} gap(s) need attention`
                    : 'No gaps found'}
                </small>
              </span>
            </Link>
            <Link to="/databricks" className="next-steps__link">
              <IconDatabricks width={18} height={18} />
              <span>
                <strong>Databricks / Gold Design</strong>
                <small>Candidate fact/dimension tables & generated SQL</small>
              </span>
            </Link>
            <Link to="/report" className="next-steps__link">
              <IconReport width={18} height={18} />
              <span>
                <strong>Assessment Report</strong>
                <small>Full write-up, exportable as PDF/Word</small>
              </span>
            </Link>
          </div>
        </section>
      )}
    </div>
  )
}
