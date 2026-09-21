import { useMemo, useState } from 'react'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Edge,
  type Node,
} from 'reactflow'
import 'reactflow/dist/style.css'
import type { LineageEdge, LineageGraphData, LineageNode } from '../../types/canonical'

const NODE_TYPE_COLOR: Record<string, string> = {
  TERADATA_SOURCE: 'var(--node-teradata)',
  SOURCE: 'var(--node-source)',
  SEMANTIC_MODEL: 'var(--node-model)',
  TABLE: 'var(--node-table)',
  COLUMN: 'var(--node-column)',
  MEASURE: 'var(--node-measure)',
}

// TERADATA_SOURCE feeds TABLE directly (not through the ingested file/model
// chain), so it sits in its own column right before TABLE rather than at
// the very front — reads as "Teradata origin -> Power BI table", parallel
// to "ingested file -> semantic model".
const NODE_TYPE_ORDER = ['SOURCE', 'SEMANTIC_MODEL', 'TERADATA_SOURCE', 'TABLE', 'MEASURE', 'COLUMN']
const NODE_WIDTH = 220
const COLUMN_GAP = 300

type TraceDirection = 'upstream' | 'downstream' | 'both'

/** Upstream = what this node depends on (follow edges forward, source ->
 * target — matches how every edge in builder.py is drawn: a measure points
 * at the measure/column it references, a column points at its table, etc.).
 * Downstream = what depends on this node (follow edges backward). */
function traceFrom(originId: string, edges: LineageEdge[], direction: TraceDirection): Set<string> {
  const forward = new Map<string, string[]>()
  const backward = new Map<string, string[]>()
  const addTo = (map: Map<string, string[]>, key: string, value: string) => {
    const list = map.get(key)
    if (list) list.push(value)
    else map.set(key, [value])
  }
  for (const e of edges) {
    addTo(forward, e.source_node_id, e.target_node_id)
    addTo(backward, e.target_node_id, e.source_node_id)
  }
  const neighborsOf = (id: string): string[] => [
    ...(direction !== 'downstream' ? forward.get(id) ?? [] : []),
    ...(direction !== 'upstream' ? backward.get(id) ?? [] : []),
  ]
  const visited = new Set<string>([originId])
  const queue = [originId]
  while (queue.length) {
    const current = queue.shift()!
    for (const next of neighborsOf(current)) {
      if (!visited.has(next)) {
        visited.add(next)
        queue.push(next)
      }
    }
  }
  return visited
}

function humanize(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

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
  const [trace, setTrace] = useState<{ originId: string; direction: TraceDirection } | null>(null)

  const filteredNodeIds = useMemo(() => {
    if (!search.trim()) return null
    const q = search.toLowerCase()
    return new Set(data.nodes.filter((n) => n.label.toLowerCase().includes(q)).map((n) => n.id))
  }, [search, data.nodes])

  // An active upstream/downstream trace takes over highlighting from search
  // (the two answer different questions — "where is X" vs. "what does X
  // touch" — showing both at once would just be two separate dim/bright
  // overlays fighting for the same nodes).
  const traceIds = useMemo(() => {
    if (!trace) return null
    return traceFrom(trace.originId, data.edges, trace.direction)
  }, [trace, data.edges])

  const highlightIds = traceIds ?? filteredNodeIds

  const nodes = useMemo(() => {
    const laidOut = layout(data.nodes)
    if (!highlightIds) return laidOut
    return laidOut.map((n) => ({
      ...n,
      style: { ...n.style, opacity: highlightIds.has(n.id) ? 1 : 0.15 },
    }))
  }, [data.nodes, highlightIds])

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
        style: {
          opacity: highlightIds
            ? highlightIds.has(e.source_node_id) && highlightIds.has(e.target_node_id)
              ? 1
              : 0.15
            : 0.6,
        },
      })),
    [data.edges, highlightIds],
  )

  const nodeById = useMemo(() => new Map(data.nodes.map((n) => [n.id, n])), [data.nodes])

  const selectNode = (node: LineageNode) => {
    setSelected(node)
    setTrace(null)
  }

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
          onNodeClick={(_, node) => {
            const found = nodeById.get(node.id)
            if (found) selectNode(found)
          }}
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

          <div className="lineage-explorer__trace-actions">
            <button
              className={trace?.direction === 'upstream' ? 'active' : ''}
              onClick={() => setTrace({ originId: selected.id, direction: 'upstream' })}
            >
              Upstream
            </button>
            <button
              className={trace?.direction === 'downstream' ? 'active' : ''}
              onClick={() => setTrace({ originId: selected.id, direction: 'downstream' })}
            >
              Downstream
            </button>
            <button
              className={trace?.direction === 'both' ? 'active' : ''}
              onClick={() => setTrace({ originId: selected.id, direction: 'both' })}
            >
              Both
            </button>
            {trace && <button onClick={() => setTrace(null)}>Clear trace</button>}
          </div>

          <DetailFields detail={selected.detail} />

          <button onClick={() => setSelected(null)}>Close</button>
        </aside>
      )}
    </div>
  )
}

function DetailFields({ detail }: { detail: Record<string, unknown> }) {
  const dax = typeof detail.expression === 'string' && detail.expression ? detail.expression : null
  const entries = Object.entries(detail).filter(([key, value]) => {
    if (key === 'expression') return false
    if (value === null || value === undefined || value === '') return false
    if (Array.isArray(value) && value.length === 0) return false
    return true
  })

  if (!dax && entries.length === 0) return null

  return (
    <div className="lineage-explorer__detail-fields">
      {dax && (
        <div className="lineage-detail-field">
          <div className="lineage-detail-field__label">DAX</div>
          <code className="dax-expr">{dax}</code>
        </div>
      )}
      {entries.map(([key, value]) => (
        <div className="lineage-detail-field" key={key}>
          <div className="lineage-detail-field__label">{humanize(key)}</div>
          <div className="lineage-detail-field__value">
            {Array.isArray(value) ? value.join(', ') : String(value)}
          </div>
        </div>
      ))}
    </div>
  )
}
