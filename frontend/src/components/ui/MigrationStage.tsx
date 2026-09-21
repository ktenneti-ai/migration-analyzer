export type StageStatus = 'complete' | 'in_progress' | 'not_started' | 'warning'

export interface StageInfo {
  key: string
  label: string
  status: StageStatus
  note: string
}

const STATUS_TEXT: Record<StageStatus, string> = {
  complete: 'Completed',
  in_progress: 'In progress',
  not_started: 'Not started',
  warning: 'Needs attention',
}

export function ProgressIndicator({ stages }: { stages: StageInfo[] }) {
  return (
    <div className="stage-flow">
      {stages.map((stage) => (
        <div className={`stage stage--${stage.status}`} key={stage.key} title={stage.note}>
          <span className="stage__dot" />
          <span>
            <span className="stage__label">{stage.label}</span>
            <span className="stage__status">{STATUS_TEXT[stage.status]}</span>
          </span>
        </div>
      ))}
    </div>
  )
}
