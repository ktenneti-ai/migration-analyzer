/**
 * Renders a table's display_name when one exists (Power BI's auto-generated
 * date tables get GUID-suffixed real names — see backend/app/ingestion/tmdl/
 * tmdl_adapter.py), with the real name printed underneath in smaller, dimmer
 * text so it's always visible rather than hidden behind a hover. Falls back
 * to just the real name when there's no friendlier name to show.
 */
export function TableName({ name, displayName }: { name: string; displayName: string | null }) {
  if (displayName) {
    return (
      <span className="table-name">
        <span className="table-name__display">{displayName}</span>
        <span className="table-name__real">{name}</span>
      </span>
    )
  }
  return <span className="table-name">{name}</span>
}
