import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { InventoryTable, StatusBadge } from './InventoryTable'

interface Row {
  name: string
  value: number
}

describe('InventoryTable', () => {
  it('renders the empty message when there are no rows', () => {
    render(
      <InventoryTable<Row>
        rows={[]}
        emptyMessage="Nothing here yet."
        getRowKey={(r) => r.name}
        columns={[{ header: 'Name', render: (r) => r.name }]}
      />,
    )
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument()
  })

  it('renders one row per item with the configured columns', () => {
    const rows: Row[] = [
      { name: 'Total Revenue', value: 1 },
      { name: 'Total Cost', value: 2 },
    ]
    render(
      <InventoryTable<Row>
        rows={rows}
        emptyMessage="Nothing here yet."
        getRowKey={(r) => r.name}
        columns={[
          { header: 'Name', render: (r) => r.name },
          { header: 'Value', render: (r) => r.value },
        ]}
      />,
    )
    expect(screen.getByText('Total Revenue')).toBeInTheDocument()
    expect(screen.getByText('Total Cost')).toBeInTheDocument()
    expect(screen.getAllByRole('row')).toHaveLength(3) // header + 2 rows
  })
})

describe('StatusBadge', () => {
  it('renders the status text', () => {
    render(<StatusBadge status="REQUIRES_INPUT" />)
    expect(screen.getByText('REQUIRES_INPUT')).toBeInTheDocument()
  })
})
