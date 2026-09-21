import type {
  AssessmentReport,
  Dashboard,
  GoldResponse,
  LineageGraphData,
  MeasureRow,
  MigrationGap,
  MigrationPhase,
  Project,
  RelationshipRow,
  SqlConversionResponse,
  TableRow,
  TeradataReferencedObject,
  TeradataUnresolvedTable,
} from '../types/canonical'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init)
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  listProjects: () => request<Project[]>('/projects'),
  createProject: (name: string) =>
    request<Project>('/projects', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name }),
    }),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  deleteProject: (id: string) => request<{ deleted: number }>(`/projects/${id}`, { method: 'DELETE' }),
  deleteAllProjects: () => request<{ deleted: number }>('/projects', { method: 'DELETE' }),
  getDashboard: (id: string) => request<Dashboard>(`/projects/${id}/dashboard`),
  getTables: (id: string) => request<TableRow[]>(`/projects/${id}/powerbi/tables`),
  getMeasures: (id: string) => request<MeasureRow[]>(`/projects/${id}/powerbi/measures`),
  getRelationships: (id: string) =>
    request<RelationshipRow[]>(`/projects/${id}/powerbi/relationships`),
  getGaps: (id: string) => request<MigrationGap[]>(`/projects/${id}/gaps`),
  getLineage: (id: string) => request<LineageGraphData>(`/projects/${id}/lineage`),
  getReport: (id: string) => request<AssessmentReport>(`/projects/${id}/report`),
  getReportExportUrl: (id: string, format: 'pdf' | 'docx') =>
    `/api/projects/${id}/report/export?format=${format}`,
  getMigrationPlan: (id: string) => request<MigrationPhase[]>(`/projects/${id}/migration-plan`),
  getSqlConversion: (id: string) =>
    request<SqlConversionResponse>(`/projects/${id}/sql-conversion`),
  getGold: (id: string) => request<GoldResponse>(`/projects/${id}/gold`),
  getTeradataReferencedObjects: (id: string) =>
    request<TeradataReferencedObject[]>(`/projects/${id}/teradata/referenced-objects`),
  getTeradataUnresolvedTables: (id: string) =>
    request<TeradataUnresolvedTable[]>(`/projects/${id}/teradata/unresolved-tables`),
  getMetricViewExportUrl: (id: string, factTable: string) =>
    `/api/projects/${id}/gold/metric-view/${encodeURIComponent(factTable)}/export`,
  getWrapperViewExportUrl: (id: string, factTable: string) =>
    `/api/projects/${id}/gold/wrapper-view/${encodeURIComponent(factTable)}/export`,
  ingestFile: async (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`/api/projects/${id}/ingest`, { method: 'POST', body: form })
    if (!res.ok) {
      const body = await res.text()
      throw new Error(`${res.status} ${res.statusText}: ${body}`)
    }
    return res.json()
  },
}
