import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { Project } from '../types/canonical'

interface ProjectContextValue {
  projectId: string | null
  setProjectId: (id: string | null) => void
  project: Project | null
  /** Bumps on every refresh() call — pages can add it to a useEffect's deps
   *  to re-fetch their own data without each page owning its own polling. */
  refreshKey: number
  refresh: () => void
}

const ProjectContext = createContext<ProjectContextValue | undefined>(undefined)

const STORAGE_KEY = 'migration-analyzer.current-project-id'

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectIdState] = useState<string | null>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY)
    } catch {
      return null
    }
  })
  const [project, setProject] = useState<Project | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const setProjectId = (id: string | null) => {
    setProjectIdState(id)
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id)
      else localStorage.removeItem(STORAGE_KEY)
    } catch {
      // localStorage may be unavailable (private browsing); state still updates in memory.
    }
  }

  useEffect(() => {
    document.title = 'Migration Analyzer'
  }, [])

  useEffect(() => {
    if (!projectId) {
      setProject(null)
      return
    }
    api.getProject(projectId).then(setProject).catch(() => setProject(null))
  }, [projectId, refreshKey])

  const refresh = () => setRefreshKey((k) => k + 1)

  return (
    <ProjectContext.Provider value={{ projectId, setProjectId, project, refreshKey, refresh }}>
      {children}
    </ProjectContext.Provider>
  )
}

export function useProject() {
  const ctx = useContext(ProjectContext)
  if (!ctx) throw new Error('useProject must be used within ProjectProvider')
  return ctx
}
