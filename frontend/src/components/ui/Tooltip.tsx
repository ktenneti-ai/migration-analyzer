import type { ReactNode } from 'react'

export function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="tooltip-wrap" tabIndex={0}>
      {children}
      <span className="tooltip-bubble">{label}</span>
    </span>
  )
}
