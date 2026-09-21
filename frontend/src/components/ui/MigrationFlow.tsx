import { Fragment } from 'react'

export interface FlowStage {
  key: string
  name: string
  count: number | null
  note?: string
}

export function MigrationFlow({ stages }: { stages: FlowStage[] }) {
  return (
    <div className="migration-flow">
      {stages.map((stage, i) => (
        <Fragment key={stage.key}>
          <div
            className={`migration-flow__stage ${stage.count === null ? 'migration-flow__stage--empty' : ''}`}
          >
            <div className="migration-flow__name">{stage.name}</div>
            {stage.count !== null ? (
              <div className="migration-flow__count">{stage.count}</div>
            ) : (
              <div className="migration-flow__note">{stage.note}</div>
            )}
          </div>
          {i < stages.length - 1 && (
            <span className="migration-flow__arrow" aria-hidden="true">
              &#8594;
            </span>
          )}
        </Fragment>
      ))}
    </div>
  )
}
