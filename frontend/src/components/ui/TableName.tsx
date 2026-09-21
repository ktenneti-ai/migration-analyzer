import { Tooltip } from './Tooltip'

/**
 * Renders a table's display_name when one exists (Power BI's auto-generated
 * date tables get GUID-suffixed real names — see backend/app/ingestion/tmdl/
 * tmdl_adapter.py), with the real name available on hover so it's never
 * hidden, just not the primary label. Falls back to the real name (with a
 * native title tooltip, in case it's unusually long) when there's no
 * friendlier name to show.
 */
export function TableName({ name, displayName }: { name: string; displayName: string | null }) {
  if (displayName) {
    return (
      <Tooltip label={`Real name: ${name}`}>
        <span className="table-name">{displayName}</span>
      </Tooltip>
    )
  }
  return (
    <span className="table-name" title={name}>
      {name}
    </span>
  )
}
