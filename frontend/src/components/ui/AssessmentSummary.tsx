import { IconDatabricks, IconGaps, IconPowerBI, IconTeradata } from '../icons/Icons'
import { MetricCard } from './MetricCard'
import type { Dashboard } from '../../types/canonical'

export function AssessmentSummary({ data }: { data: Dashboard }) {
  const powerBiTotal = data.semantic_models + data.tables + data.columns + data.measures + data.relationships
  // teradata_views/teradata_base_tables are a breakdown OF
  // teradata_referenced_objects (classified from each object's own "V_"
  // naming convention), not additional objects on top of it — summing all
  // three would double-count.
  const teradataTotal = data.teradata_referenced_objects
  const databricksTotal = data.bronze_tables + data.silver_tables + data.gold_facts + data.gold_dimensions

  return (
    <div className="kpi-grid">
      <MetricCard
        icon={<IconPowerBI />}
        iconColor="var(--node-table)"
        value={powerBiTotal}
        label="Power BI Objects"
        sub={`${data.semantic_models} Model${data.semantic_models === 1 ? '' : 's'} • ${data.tables} Tables • ${data.columns} Columns • ${data.measures} Measures • ${data.relationships} Relationships`}
      />
      <MetricCard
        icon={<IconTeradata />}
        iconColor="var(--node-teradata)"
        value={teradataTotal}
        label="Teradata Objects"
        sub={
          teradataTotal > 0
            ? `${data.teradata_views} Views • ${data.teradata_base_tables} Base Tables (via Power BI)`
            : 'Teradata discovery not completed'
        }
      />
      <MetricCard
        icon={<IconDatabricks />}
        iconColor="var(--primary)"
        value={databricksTotal}
        label="Databricks Objects"
        sub={
          databricksTotal > 0
            ? `${data.bronze_tables} Bronze • ${data.silver_tables} Silver • ${data.gold_facts} Gold Facts • ${data.gold_dimensions} Gold Dims`
            : 'Databricks target not yet designed'
        }
      />
      <MetricCard
        icon={<IconGaps />}
        iconColor="var(--node-column)"
        value={data.migration_gaps}
        label="Migration Gaps"
        sub={data.migration_gaps > 0 ? 'Requires attention' : 'None identified yet'}
      />
    </div>
  )
}
