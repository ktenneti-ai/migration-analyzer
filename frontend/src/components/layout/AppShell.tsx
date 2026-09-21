import type { ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { TopHeader } from './TopHeader'

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-body">
        <TopHeader />
        <main className="app-main">{children}</main>
      </div>
    </div>
  )
}
