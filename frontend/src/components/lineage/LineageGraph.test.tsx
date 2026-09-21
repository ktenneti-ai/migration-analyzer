import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { LineageGraphData } from '../../types/canonical'
import { LineageGraph } from './LineageGraph'

const fixture: LineageGraphData = {
  nodes: [
    { id: 'm1', node_type: 'SEMANTIC_MODEL', ref_id: 'm1', label: 'Finance' },
    { id: 't1', node_type: 'TABLE', ref_id: 't1', label: 'FactSales' },
    { id: 'c1', node_type: 'COLUMN', ref_id: 'c1', label: 'FactSales.Revenue' },
    { id: 'me1', node_type: 'MEASURE', ref_id: 'me1', label: 'Total Revenue' },
  ],
  edges: [
    { id: 'e1', source_node_id: 't1', target_node_id: 'm1', edge_type: 'TABLE_TO_MODEL' },
    { id: 'e2', source_node_id: 'c1', target_node_id: 't1', edge_type: 'COLUMN_TO_TABLE' },
    { id: 'e3', source_node_id: 'me1', target_node_id: 'c1', edge_type: 'MEASURE_TO_COLUMN' },
  ],
}

describe('LineageGraph', () => {
  it('renders a search box and the legend for every node type', () => {
    render(<LineageGraph data={fixture} />)
    expect(screen.getByPlaceholderText(/search nodes/i)).toBeInTheDocument()
    expect(screen.getByText('SEMANTIC MODEL')).toBeInTheDocument()
    expect(screen.getByText('TABLE')).toBeInTheDocument()
    expect(screen.getByText('COLUMN')).toBeInTheDocument()
    expect(screen.getByText('MEASURE')).toBeInTheDocument()
  })
})
