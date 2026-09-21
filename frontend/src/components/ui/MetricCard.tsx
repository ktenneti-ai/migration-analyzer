import type { ReactNode } from 'react'

export function MetricCard({
  icon,
  value,
  label,
  sub,
}: {
  icon: ReactNode
  value: number | string
  label: string
  sub?: string
}) {
  return (
    <div className="kpi-card">
      <div className="kpi-card__top">
        <span className="kpi-card__icon">{icon}</span>
      </div>
      <div className="kpi-card__value">{value}</div>
      <div className="kpi-card__label">{label}</div>
      {sub && <div className="kpi-card__sub">{sub}</div>}
    </div>
  )
}
