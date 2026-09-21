import { useMemo, useState } from 'react'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Edge,
  type Node,
} from 'reactflow'
import 'reactflow/dist/style.css'
import type { LineageGraphData, LineageNode } from '../../types/canonical'

const NODE_TYPE_COLOR: Record<string, string> = {
  SEMANTIC_MODEL: 'var(--node-model)',
  TABLE: 'var(--node-table)',
  COLUMN: 'var(--node-column)',
  MEASURE: 'var(--node-measure)',
}

const NODE_TYPE_ORDER = ['SEMANTIC_MODEL', 'TABLE', 'MEASURE', 'COLUMN']
const NODE_WIDTH = 220
const COLUMN_GAP = 300

function layout(nodes: LineageNode[]): Node[] {
  const byType = new Map<string, LineageNode[]>()
  for (const n of nodes) {
    const list = byType.get(n.node_type) ?? []
    list.push(n)
    byType.set(n.node_type, list)
  }

  const result: Node[] = []
  NODE_TYPE_ORDER.forEach((type, col) => {
    const items = byType.get(type) ?? []
    items.forEach((n, row) => {
      result.push({
        id: n.id,
        position: { x: col * COLUMN_GAP, y: row * 60 },
        data: { label: n.label, nodeType: n.node_type },
        // A fixed width with wrapping (rather than letting the label size the
        // box) keeps long real table names and derived date-table labels
        // from spilling into the next column and overlapping other nodes.
        style: {
          width: NODE_WIDTH,
          borderColor: NODE_TYPE_COLOR[n.node_type] ?? 'var(--rule)',
          borderWidth: 1.5,
          borderStyle: 'solid',
          borderRadius: 2,
          padding: 8,
          fontSize: 12,
          fontFamily: 'var(--font-mono)',
          background: 'var(--panel)',
          color: 'var(--text)',
          whiteSpace: 'normal',
          wordBreak: 'break-word',
          textAlign: 'left' as const,
        },
      })
    })
  })
  return result
}

export function LineageGraph({ data }: { data: LineageGraphData }) {
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<LineageNode | null>(null)

  const filteredNodeIds = useMemo(() => {
    if (!search.trim()) return null
    const q = search.toLowerCase()
    return new Set(data.nodes.filter((n) => n.label.toLowerCase().includes(q)).map((n) => n.id))
  }, [search, data.nodes])

  const nodes = useMemo(() => {
    const laidOut = layout(data.nodes)
    if (!filteredNodeIds) return laidOut
    return laidOut.map((n) => ({
      ...n,
      style: { ...n.style, opacity: filteredNodeIds.has(n.id) ? 1 : 0.15 },
    }))
  }, [data.nodes, filteredNodeIds])

  const edges: Edge[] = useMemo(
    () =>
      data.edges.map((e) => ({
        id: e.id,
        source: e.source_node_id,
        target: e.target_node_id,
        // Containment/relationship edges are obvious from the node colors and
        // arrow direction alone — labeling every one of them just repeats
        // "TABLE_TO_TABLE" across the canvas. Only the measure-dependency
        // edges carry information a table-relationship diagram doesn't.
        label: e.edge_type.startsWith('MEASURE') ? e.edge_type : undefined,
        animated: e.edge_type.startsWith('MEASURE'),
        style: { opacity: filteredNodeIds ? 0.3 : 0.6 },
      })),
    [data.edges, filteredNodeIds],
  )

  const nodeById = useMemo(() => new Map(data.nodes.map((n) => [n.id, n])), [data.nodes])

  return (
    <div className="lineage-explorer">
      <div className="lineage-explorer__toolbar">
        <input
          type="search"
          placeholder="Search nodes (measure, table, column)..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="legend">
          {Object.entries(NODE_TYPE_COLOR).map(([type, color]) => (
            <span key={type} className="legend__item">
              <span className="legend__swatch" style={{ background: color }} />
              {type.replace('_', ' ')}
            </span>
          ))}
        </div>
      </div>
      <div className="lineage-explorer__canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          onNodeClick={(_, node) => setSelected(nodeById.get(node.id) ?? null)}
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
      {selected && (
        <aside className="lineage-explorer__detail">
          <h4>{selected.label}</h4>
          <p className="muted">{selected.node_type}</p>
          <button onClick={() => setSelected(null)}>Close</button>
        </aside>
      )}
    </div>
  )
}
