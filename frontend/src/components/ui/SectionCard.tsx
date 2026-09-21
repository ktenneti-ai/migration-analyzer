import type { ReactNode } from 'react'

export function SectionCard({
  title,
  action,
  children,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="card">
      <div className="card__header">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

export function MetricRow({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="metric-row">
      <span className="metric-row__label">{label}</span>
      <span className="metric-row__value">{value}</span>
    </div>
  )
}
