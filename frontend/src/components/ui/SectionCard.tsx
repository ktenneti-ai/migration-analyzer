import type { CSSProperties, ReactNode } from 'react'

export function SectionCard({
  title,
  action,
  children,
  accent,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
  // Optional colored top border (a CSS color/var), used sparingly to give a
  // tile a domain identity (e.g. matching the Power BI/Teradata/Databricks
  // colors used in the sidebar and lineage graph). Omitted entirely for the
  // vast majority of SectionCard usages across the app, which keep the
  // plain flat panel look.
  accent?: string
}) {
  return (
    <section
      className={`card ${accent ? 'card--accent' : ''}`}
      style={accent ? ({ '--card-accent': accent } as CSSProperties) : undefined}
    >
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
