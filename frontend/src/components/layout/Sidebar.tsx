import { useState, type ReactElement } from 'react'
import { NavLink } from 'react-router-dom'
import {
  IconChevronLeft,
  IconDashboard,
  IconDatabricks,
  IconExports,
  IconGaps,
  IconLineage,
  IconPlan,
  IconPowerBI,
  IconProjects,
  IconReport,
  IconSettings,
  IconSql,
  IconTeradata,
  IconValidation,
} from '../icons/Icons'

interface NavItem {
  to: string
  label: string
  icon: (props: { width?: number; height?: number }) => ReactElement
  end?: boolean
  // Fixed per-item accent for the icon only (never the label) — reuses the
  // same palette already assigned to lineage-graph node types where the
  // subject matches (Power BI -> table blue, Teradata -> its lineage-node
  // orange, Lineage itself -> model purple), so the color means the same
  // thing wherever it appears in the app. Deliberately never
  // success/warning/danger — those are reserved for the CONFIRMED/INFERRED/
  // REQUIRES_INPUT status grammar, and reusing them here would make a plain
  // nav icon look like a status indicator.
  color: string
}

interface NavGroup {
  label: string
  items: NavItem[]
}

const GROUPS: NavGroup[] = [
  {
    label: 'Overview',
    items: [
      { to: '/', label: 'Dashboard', icon: IconDashboard, end: true, color: 'var(--secondary)' },
      { to: '/upload', label: 'Projects', icon: IconProjects, color: 'var(--node-source)' },
    ],
  },
  {
    label: 'Assessment',
    items: [
      { to: '/powerbi/tables', label: 'Power BI', icon: IconPowerBI, color: 'var(--node-table)' },
      { to: '/teradata', label: 'Teradata', icon: IconTeradata, color: 'var(--node-teradata)' },
      { to: '/lineage', label: 'Lineage', icon: IconLineage, color: 'var(--node-model)' },
      { to: '/gaps', label: 'Gaps', icon: IconGaps, color: 'var(--node-column)' },
    ],
  },
  {
    label: 'Migration',
    items: [
      { to: '/databricks', label: 'Databricks', icon: IconDatabricks, color: 'var(--primary)' },
      { to: '/sql-conversion', label: 'SQL Conversion', icon: IconSql, color: 'var(--node-measure)' },
      { to: '/migration-plan', label: 'Migration Plan', icon: IconPlan, color: 'var(--secondary)' },
      { to: '/validation', label: 'Validation', icon: IconValidation, color: 'var(--node-column)' },
    ],
  },
  {
    label: 'Output',
    items: [
      { to: '/report', label: 'Assessment Report', icon: IconReport, color: 'var(--node-source)' },
      { to: '/exports', label: 'Exports', icon: IconExports, color: 'var(--node-measure)' },
    ],
  },
  {
    label: 'System',
    items: [{ to: '/settings', label: 'Settings', icon: IconSettings, color: 'var(--text-dim)' }],
  },
]

const STORAGE_KEY = 'migration-analyzer.sidebar-collapsed'

function LineageMark() {
  return (
    <svg className="sidebar__mark" width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path d="M4 4L9 9M9 9L14 4M9 9V15" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="4" cy="4" r="2" fill="currentColor" />
      <circle cx="14" cy="4" r="2" fill="currentColor" />
      <circle cx="9" cy="9" r="2" fill="currentColor" />
      <circle cx="9" cy="15" r="2" fill="currentColor" />
    </svg>
  )
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === '1'
    } catch {
      return false
    }
  })

  const toggle = () => {
    setCollapsed((c) => {
      const next = !c
      try {
        localStorage.setItem(STORAGE_KEY, next ? '1' : '0')
      } catch {
        // per-viewer convenience only
      }
      return next
    })
  }

  return (
    <nav className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''}`}>
      <div className="sidebar__brand">
        <LineageMark />
        {!collapsed && 'Migration Analyzer'}
      </div>
      <div className="sidebar__scroll">
        {GROUPS.map((group) => (
          <div className="sidebar__group" key={group.label}>
            <div className="sidebar__group-label">{group.label}</div>
            <ul className="sidebar__list">
              {group.items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) => `sidebar__link ${isActive ? 'active' : ''}`}
                    title={collapsed ? item.label : undefined}
                  >
                    <span className="sidebar__icon" style={{ color: item.color }}>
                      <item.icon />
                    </span>
                    {!collapsed && item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="sidebar__footer">
        <button
          type="button"
          className="sidebar__collapse-btn"
          onClick={toggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <IconChevronLeft />
          {!collapsed && 'Collapse'}
        </button>
      </div>
    </nav>
  )
}
