import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PageHeader } from '../components/layout/PageHeader'
import { StatusBadge } from '../components/tables/InventoryTable'
import { SkeletonStack } from '../components/ui/Skeleton'
import { useProject } from '../state/ProjectContext'
import type { MigrationPhase } from '../types/canonical'
import { NoProjectSelected } from './NoProjectSelected'

export function MigrationPlan() {
  const { projectId, refreshKey } = useProject()
  const [phases, setPhases] = useState<MigrationPhase[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    setPhases(null)
    api.getMigrationPlan(projectId).then(setPhases).catch((e) => setError(String(e)))
  }, [projectId, refreshKey])

  if (!projectId) return <NoProjectSelected />
  if (error) return <p className="status-msg status-msg--error">{error}</p>

  return (
    <div className="page">
      <PageHeader title="Migration Plan" subtitle="Nine phases, from discovery through cutover." />
      {!phases ? (
        <SkeletonStack rows={5} />
      ) : (
        <div className="phase-list">
          {phases.map((phase) => (
            <div className={`card phase-card phase-card--${phase.status.toLowerCase()}`} key={phase.key}>
              <div className="report-section__header">
                <h2>{phase.name}</h2>
                <StatusBadge status={phase.status} />
              </div>
              <ul className="report-section__details">
                {phase.tasks.map((task) => (
                  <li key={task}>{task}</li>
                ))}
              </ul>
              {phase.blocked_reason && <p className="status-msg status-msg--error">{phase.blocked_reason}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
