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
}

interface NavGroup {
  label: string
  items: NavItem[]
}

const GROUPS: NavGroup[] = [
  {
    label: 'Overview',
    items: [
      { to: '/', label: 'Dashboard', icon: IconDashboard, end: true },
      { to: '/upload', label: 'Projects', icon: IconProjects },
    ],
  },
  {
    label: 'Assessment',
    items: [
      { to: '/powerbi/tables', label: 'Power BI', icon: IconPowerBI },
      { to: '/teradata', label: 'Teradata', icon: IconTeradata },
      { to: '/lineage', label: 'Lineage', icon: IconLineage },
      { to: '/gaps', label: 'Gaps', icon: IconGaps },
    ],
  },
  {
    label: 'Migration',
    items: [
      { to: '/databricks', label: 'Databricks', icon: IconDatabricks },
      { to: '/sql-conversion', label: 'SQL Conversion', icon: IconSql },
      { to: '/migration-plan', label: 'Migration Plan', icon: IconPlan },
      { to: '/validation', label: 'Validation', icon: IconValidation },
    ],
  },
  {
    label: 'Output',
    items: [
      { to: '/report', label: 'Assessment Report', icon: IconReport },
      { to: '/exports', label: 'Exports', icon: IconExports },
    ],
  },
  {
    label: 'System',
    items: [{ to: '/settings', label: 'Settings', icon: IconSettings }],
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
                    <item.icon />
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
