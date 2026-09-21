import type { CSSProperties } from 'react'
import { NavLink } from 'react-router-dom'

// Same per-domain accent used for the active underline as everywhere else
// color-coded in the app (sidebar nav, lineage graph nodes) — set via a CSS
// custom property so the plain .tab-bar a.active rule can read it, falling
// back to the app's primary accent when unset.
const TABS: { to: string; label: string; color: string }[] = [
  { to: '/powerbi/tables', label: 'Tables', color: 'var(--node-table)' },
  { to: '/powerbi/measures', label: 'Measures', color: 'var(--node-measure)' },
  { to: '/powerbi/relationships', label: 'Relationships', color: 'var(--node-column)' },
]

export function PowerBITabs() {
  return (
    <div className="tab-bar">
      {TABS.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          className={({ isActive }) => (isActive ? 'active' : '')}
          style={{ '--tab-accent': tab.color } as CSSProperties}
        >
          {tab.label}
        </NavLink>
      ))}
    </div>
  )
}
