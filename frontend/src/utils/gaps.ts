import type { MigrationGap } from '../types/canonical'

// The backend's object_ref is always "<Kind>:<name>" (e.g. "Measure:Total
// Revenue" — see backend/app/parsers/dax/dependency_parser.py). This derives
// a human "Source" grouping and a plain object name from that real,
// stable format rather than inventing a field the API doesn't provide.
const KIND_TO_SOURCE: Record<string, string> = {
  Measure: 'Power BI',
}

export function gapSource(gap: MigrationGap): string {
  const kind = gap.object_ref.split(':')[0]
  return KIND_TO_SOURCE[kind] ?? kind
}

export function gapObjectName(gap: MigrationGap): string {
  const idx = gap.object_ref.indexOf(':')
  return idx === -1 ? gap.object_ref : gap.object_ref.slice(idx + 1)
}
