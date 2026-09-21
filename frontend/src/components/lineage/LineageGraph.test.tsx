import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { LineageGraphData } from '../../types/canonical'
import { LineageGraph } from './LineageGraph'

const fixture: LineageGraphData = {
  nodes: [
    { id: 's1', node_type: 'SOURCE', ref_id: 'finance.tmdl', label: 'finance.tmdl', is_system: false, detail: {} },
    {
      id: 'm1',
      node_type: 'SEMANTIC_MODEL',
      ref_id: 'm1',
      label: 'Finance',
      is_system: false,
      detail: { tables: 1, relationships: 0 },
    },
    {
      id: 'td1',
      node_type: 'TERADATA_SOURCE',
      ref_id: 'Teradata: BNRPROD.CP_ED.V_CPED_FACT_SALES',
      label: 'BNRPROD.CP_ED.V_CPED_FACT_SALES',
      is_system: false,
      detail: { database: 'BNRPROD', schema: 'CP_ED', object: 'V_CPED_FACT_SALES' },
    },
    {
      id: 't1',
      node_type: 'TABLE',
      ref_id: 't1',
      label: 'FactSales',
      is_system: false,
      detail: { real_name: 'FactSales', columns: 1, measures: 1 },
    },
    {
      id: 'c1',
      node_type: 'COLUMN',
      ref_id: 'c1',
      label: 'FactSales.Revenue',
      is_system: false,
      detail: { table: 'FactSales', data_type: 'DECIMAL' },
    },
    {
      id: 'me1',
      node_type: 'MEASURE',
      ref_id: 'me1',
      label: 'Total Revenue',
      is_system: false,
      detail: { expression: 'SUM(FactSales[Revenue])', referenced_columns: ['FactSales.Revenue'] },
    },
  ],
  edges: [
    { id: 'e0', source_node_id: 's1', target_node_id: 'm1', edge_type: 'SOURCE_TO_MODEL' },
    { id: 'e0b', source_node_id: 'td1', target_node_id: 't1', edge_type: 'TERADATA_TO_TABLE' },
    { id: 'e1', source_node_id: 't1', target_node_id: 'm1', edge_type: 'TABLE_TO_MODEL' },
    { id: 'e2', source_node_id: 'c1', target_node_id: 't1', edge_type: 'COLUMN_TO_TABLE' },
    { id: 'e3', source_node_id: 'me1', target_node_id: 'c1', edge_type: 'MEASURE_TO_COLUMN' },
  ],
}

describe('LineageGraph', () => {
  it('renders a search box and the legend for every node type', () => {
    render(<LineageGraph data={fixture} />)
    expect(screen.getByPlaceholderText(/search nodes/i)).toBeInTheDocument()
    expect(screen.getByText('SOURCE')).toBeInTheDocument()
    expect(screen.getByText('TERADATA SOURCE')).toBeInTheDocument()
    expect(screen.getByText('SEMANTIC MODEL')).toBeInTheDocument()
    expect(screen.getByText('TABLE')).toBeInTheDocument()
    expect(screen.getByText('COLUMN')).toBeInTheDocument()
    expect(screen.getByText('MEASURE')).toBeInTheDocument()
  })

  it('shows DAX and dependency details, and traces upstream, when a measure node is clicked', async () => {
    const { container } = render(<LineageGraph data={fixture} />)
    const measureNode = container.querySelector('.react-flow__node[data-id="me1"]')
    expect(measureNode).not.toBeNull()
    const { fireEvent } = await import('@testing-library/react')
    fireEvent.click(measureNode!)

    const panel = container.querySelector('.lineage-explorer__detail')
    expect(panel).not.toBeNull()
    expect(panel!.textContent).toContain('SUM(FactSales[Revenue])')
    expect(panel!.textContent).toContain('FactSales.Revenue')

    fireEvent.click(screen.getByRole('button', { name: 'Upstream' }))
    expect(screen.getByRole('button', { name: 'Clear trace' })).toBeInTheDocument()
  })
})
