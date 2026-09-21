import { NavLink } from 'react-router-dom'

export function PowerBITabs() {
  return (
    <div className="tab-bar">
      <NavLink to="/powerbi/tables" className={({ isActive }) => (isActive ? 'active' : '')}>
        Tables
      </NavLink>
      <NavLink to="/powerbi/measures" className={({ isActive }) => (isActive ? 'active' : '')}>
        Measures
      </NavLink>
      <NavLink to="/powerbi/relationships" className={({ isActive }) => (isActive ? 'active' : '')}>
        Relationships
      </NavLink>
    </div>
  )
}
