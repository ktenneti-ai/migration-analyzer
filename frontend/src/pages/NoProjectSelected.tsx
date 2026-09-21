import { Link } from 'react-router-dom'

export function NoProjectSelected() {
  return (
    <div className="page">
      <p className="empty-state">
        No project selected. <Link to="/upload">Create or select a project</Link> to get started.
      </p>
    </div>
  )
}
