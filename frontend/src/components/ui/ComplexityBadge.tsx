export type ComplexityLevel = 'LOW' | 'MEDIUM' | 'HIGH'

export function ComplexityBadge({ level }: { level: ComplexityLevel }) {
  return <span className={`complexity-badge complexity-badge--${level.toLowerCase()}`}>{level}</span>
}

export function ComplexityBar({ low, medium, high }: { low: number; medium: number; high: number }) {
  const total = low + medium + high
  if (total === 0) {
    return (
      <>
        <div className="segmented-bar">
          <div className="segmented-bar__segment--low" style={{ width: '0%' }} />
        </div>
        <p className="muted">Complexity classification is not yet available for this project.</p>
      </>
    )
  }
  return (
    <>
      <div className="segmented-bar">
        <div className="segmented-bar__segment--low" style={{ width: `${(low / total) * 100}%` }} />
        <div className="segmented-bar__segment--medium" style={{ width: `${(medium / total) * 100}%` }} />
        <div className="segmented-bar__segment--high" style={{ width: `${(high / total) * 100}%` }} />
      </div>
      <div className="segmented-bar-legend">
        <span className="segmented-bar-legend__item">
          <span className="segmented-bar-legend__swatch" style={{ background: 'var(--success)' }} />
          Low ({low})
        </span>
        <span className="segmented-bar-legend__item">
          <span className="segmented-bar-legend__swatch" style={{ background: 'var(--warning)' }} />
          Medium ({medium})
        </span>
        <span className="segmented-bar-legend__item">
          <span className="segmented-bar-legend__swatch" style={{ background: 'var(--danger)' }} />
          High ({high})
        </span>
      </div>
    </>
  )
}
