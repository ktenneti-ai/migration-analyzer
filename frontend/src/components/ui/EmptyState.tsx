import type { ReactNode } from 'react'

export function EmptyState({
  icon,
  title,
  body,
}: {
  icon?: ReactNode
  title: string
  body: string
}) {
  return (
    <div className="card empty-state-panel">
      {icon && <span className="empty-state-panel__icon">{icon}</span>}
      <div>
        <div className="empty-state-panel__title">{title}</div>
        <p className="empty-state-panel__body">{body}</p>
      </div>
    </div>
  )
}
