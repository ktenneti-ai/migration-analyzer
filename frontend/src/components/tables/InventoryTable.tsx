import type { ReactNode } from 'react'
import type { Status } from '../../types/canonical'

export interface Column<T> {
  header: string
  render: (row: T) => ReactNode
}

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`status-badge status-badge--${status.toLowerCase()}`}>{status}</span>
}

export function InventoryTable<T>({
  columns,
  rows,
  emptyMessage,
  getRowKey,
}: {
  columns: Column<T>[]
  rows: T[]
  emptyMessage: string
  getRowKey: (row: T, index: number) => string
}) {
  if (rows.length === 0) {
    return <p className="empty-state">{emptyMessage}</p>
  }
  return (
    <div className="table-card">
      <table>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.header}>{col.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={getRowKey(row, i)}>
              {columns.map((col) => (
                <td key={col.header}>{col.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
