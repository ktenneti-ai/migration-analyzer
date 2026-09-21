import type { ReactNode } from 'react'

export function MetricCard({
  icon,
  value,
  label,
  sub,
  iconColor,
}: {
  icon: ReactNode
  value: number | string
  label: string
  sub?: string
  // Fixed accent for the icon only — same palette used for this domain
  // everywhere else (sidebar nav, lineage graph nodes). Falls back to the
  // existing neutral dim color when omitted.
  iconColor?: string
}) {
  return (
    <div className="kpi-card">
      <div className="kpi-card__top">
        <span className="kpi-card__icon" style={iconColor ? { color: iconColor } : undefined}>
          {icon}
        </span>
      </div>
      <div className="kpi-card__value">{value}</div>
      <div className="kpi-card__label">{label}</div>
      {sub && <div className="kpi-card__sub">{sub}</div>}
    </div>
  )
}
