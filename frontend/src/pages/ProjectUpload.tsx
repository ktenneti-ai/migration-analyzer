import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { PageHeader } from '../components/layout/PageHeader'
import { useProject } from '../state/ProjectContext'
import type { Project } from '../types/canonical'

export function ProjectUpload() {
  const { projectId, setProjectId, refresh: refreshShellData } = useProject()
  const [projects, setProjects] = useState<Project[]>([])
  const [newName, setNewName] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const refreshList = () => api.listProjects().then(setProjects).catch((e) => setError(String(e)))

  useEffect(() => {
    refreshList()
  }, [])

  const createProject = async () => {
    if (!newName.trim()) return
    const project = await api.createProject(newName.trim())
    setNewName('')
    await refreshList()
    setProjectId(project.id)
  }

  const uploadFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    if (!projectId) {
      setError('Select or create a project first.')
      return
    }
    setError(null)
    for (const file of Array.from(files)) {
      try {
        const result = await api.ingestFile(projectId, file)
        setStatus(
          `${file.name}: detected ${result.detected_schema}, extracted ${result.tables_extracted} table(s), ${result.measures_extracted} measure(s), ${result.gaps_found} gap(s) found.`,
        )
      } catch (e) {
        setError(`${file.name}: ${String(e)}`)
      }
    }
    await refreshList()
    refreshShellData() // so the dashboard, header "last analyzed", etc. pick up the new data
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
        <h2>Select a project</h2>
        {projects.length === 0 ? (
          <p className="empty-state">No projects yet — create one above.</p>
        ) : (
          <ul className="project-list">
            {projects.map((p) => (
              <li key={p.id} className={p.id === projectId ? 'active' : ''}>
                <button onClick={() => setProjectId(p.id)}>{p.name}</button>
                <span className="muted">{p.source_artifacts.length} file(s) ingested</span>
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
          {currentProject ? `Uploading into "${currentProject.name}".` : 'Select a project above first.'}
          {' '}Milestone 1 supports .json files only.
        </p>
        <div className="upload-dropzone__target" onClick={() => fileInput.current?.click()}>
          Drag & drop JSON files here, or click to browse.
        </div>
        <input
          ref={fileInput}
          type="file"
          accept=".json"
          multiple
          hidden
          onChange={(e) => uploadFiles(e.target.files)}
        />
        {status && <p className="status-msg status-msg--ok">{status}</p>}
        {error && <p className="status-msg status-msg--error">{error}</p>}
      </section>
    </div>
  )
}
