"""Maps a TMDL semantic-model script into the same canonical model the JSON
adapter produces (spec section 3: one canonical model, one adapter per
input format) — everything downstream (dependency resolution, DAX
classification, Gold design, SQL translation, Metric View YAML, wrapper
views) works unchanged regardless of which adapter populated the model.

Only `table`/`column`/`measure`/`relationship` are extracted, plus one thing
out of `partition`: a Teradata source table named via `Teradata.Database(...)
{[Schema=...]}{[Name=...]}` in the partition's M query (see
`_extract_teradata_source_hint`) — this is real upstream lineage sitting in
the file, and pbi-unified's source-table-analysis.md treats `source_hint` as
"the starting clue for the data source", so leaving it None for every
TMDL-ingested table was a real gap, not a deliberate scope cut. `hierarchy`
and `variation` blocks are still recognized by the parser but not mapped —
neither has a home in the canonical model yet.
"""
from __future__ import annotations

import re

from app.ingestion.tmdl.parser import (
    collect_properties,
    find_all,
    parse_name_and_expression,
    parse_tmdl,
    split_table_column,
)
from app.metadata.models import (
    PowerBIColumn,
    PowerBIMeasure,
    PowerBIRelationship,
    PowerBISemanticModel,
    PowerBITable,
    Provenance,
    Status,
)
from app.metadata.store import new_id

# Power BI's "Auto Date/Time" feature generates one hidden calendar table per
# date/datetime column, named e.g. "LocalDateTable_75add05e-23ff-..." or
# "DateTableTemplate_d977eeea-...". These GUID-suffixed names are meaningless
# in an inventory UI. Both variants mark themselves with one of these
# annotations (per pbi-unified's references/pitfalls.md #8: "columns[].
# variations[] -> Skip — PBI auto-date hierarchy artifact" — the artifact is
# this table, reached via a column's `variation` block).
_AUTO_DATE_ANNOTATIONS = {"__PBI_LocalDateTable", "__PBI_TemplateDateTable"}


def _is_auto_date_table(table_node) -> bool:
    for child in table_node.children:
        if child.keyword.lower() != "annotation":
            continue
        ann_name, ann_value = parse_name_and_expression(child.rest)
        if ann_name in _AUTO_DATE_ANNOTATIONS and (ann_value or "").strip().lower() == "true":
            return True
    return False


# A table imported from Teradata typically has a partition whose M query
# looks like:
#     Source = Teradata.Database("BNRPROD", [HierarchicalNavigation=true]),
#     CP_ED = Source{[Schema="CP_ED"]}[Data],
#     V_X = CP_ED{[Name="V_CPED_X"]}[Data]
# Regex over the M text (consistent with this codebase's DAX handling — no
# full M parser) rather than trying to interpret the M language generally.
# Exported so downstream readers of source_hint (the teradata.py API routes,
# the lineage graph builder) parse it back apart with the same prefix,
# rather than each re-declaring their own copy of the literal.
TERADATA_SOURCE_HINT_PREFIX = "Teradata: "
_TERADATA_DATABASE_RE = re.compile(r'Teradata\.Database\(\s*"([^"]+)"')
_M_SCHEMA_RE = re.compile(r'Schema\s*=\s*"([^"]+)"')
_M_TABLE_NAME_RE = re.compile(r'Name\s*=\s*"([^"]+)"')

# Confirmed naming convention (not an app-invented inference): this
# Teradata environment prefixes every view with "V_" — a base table has no
# such prefix. Exported so every reader of a parsed Teradata object name
# (teradata.py's API routes, compute_dashboard, the lineage graph builder)
# classifies it the same way instead of re-deriving the rule.
_TERADATA_VIEW_PREFIX = "V_"


def parse_teradata_source_hint(source_hint: str) -> dict:
    """Splits a "Teradata: DATABASE.SCHEMA.OBJECT" hint (as produced by
    _extract_teradata_source_hint) back into its parts, plus an object_type
    classification (VIEW/BASE_TABLE/None) from the "V_" naming convention."""
    parts = source_hint[len(TERADATA_SOURCE_HINT_PREFIX) :].split(".")
    database = parts[0] if len(parts) > 0 else None
    schema = parts[1] if len(parts) > 1 else None
    obj = parts[2] if len(parts) > 2 else None
    object_type = None
    if obj:
        object_type = "VIEW" if obj.upper().startswith(_TERADATA_VIEW_PREFIX) else "BASE_TABLE"
    return {"database": database, "schema": schema, "object": obj, "object_type": object_type}


def _extract_teradata_source_hint(table_node) -> str | None:
    for partition_node in table_node.children:
        if partition_node.keyword.lower() != "partition":
            continue
        source_node = next((c for c in partition_node.children if c.keyword.lower() == "source"), None)
        if source_node is None:
            continue
        # The M query lands either entirely in source_node.rest (when TMDL
        # fences it with ```) or spread across source_node's children (when
        # it isn't fenced, so the generic tokenizer split each M step into
        # its own node) — checking both covers either export shape.
        blob = " ".join(
            [source_node.rest] + [f"{c.keyword} {c.rest}" for c in source_node.children]
        )
        db_match = _TERADATA_DATABASE_RE.search(blob)
        if not db_match:
            continue
        schema_match = _M_SCHEMA_RE.search(blob)
        name_match = _M_TABLE_NAME_RE.search(blob)
        parts = [
            m.group(1)
            for m in (db_match, schema_match, name_match)
            if m is not None
        ]
        return TERADATA_SOURCE_HINT_PREFIX + ".".join(parts)
    return None


def extract_semantic_model_from_tmdl(
    raw_text: str, *, source_file: str, project_id: str, model_name: str
) -> PowerBISemanticModel:
    roots = parse_tmdl(raw_text)
    model_id = new_id()

    def prov(locator: str) -> Provenance:
        return Provenance(source_file=source_file, source_type="tmdl", json_path=locator)

    tables: list[PowerBITable] = []
    auto_date_table_names: set[str] = set()

    for table_node in find_all(roots, "table"):
        name, _ = parse_name_and_expression(table_node.rest)
        table_id = new_id()
        table_locator = f"table[{name}]:line{table_node.line_no}"
        if _is_auto_date_table(table_node):
            auto_date_table_names.add(name)

        columns: list[PowerBIColumn] = []
        measures: list[PowerBIMeasure] = []
        for child in table_node.children:
            key = child.keyword.lower()
            if key == "column":
                col_name, col_expr = parse_name_and_expression(child.rest)
                col_props = collect_properties(child.children)
                columns.append(
                    PowerBIColumn(
                        id=new_id(),
                        table_id=table_id,
                        name=col_name,
                        data_type=col_props.get("dataType"),
                        is_calculated=col_expr is not None,
                        expression=col_expr,
                        hidden=col_props.get("isHidden") == "true",
                        status=Status.CONFIRMED,
                        provenance=prov(f"{table_locator}.column[{col_name}]"),
                    )
                )
            elif key == "measure":
                meas_name, meas_expr = parse_name_and_expression(child.rest)
                measures.append(
                    PowerBIMeasure(
                        id=new_id(),
                        table_id=table_id,
                        name=meas_name,
                        expression=meas_expr or "",
                        status=Status.CONFIRMED if meas_expr else Status.REQUIRES_INPUT,
                        provenance=prov(f"{table_locator}.measure[{meas_name}]"),
                    )
                )
            # hierarchy / variation: not part of the canonical model yet —
            # intentionally skipped. partition is read for its Teradata
            # source hint (below), otherwise skipped too.

        tables.append(
            PowerBITable(
                id=table_id,
                model_id=model_id,
                name=name,
                table_type="REGULAR",
                source_hint=_extract_teradata_source_hint(table_node),
                columns=columns,
                measures=measures,
                status=Status.CONFIRMED,
                provenance=prov(table_locator),
            )
        )

    relationships: list[PowerBIRelationship] = []
    for rel_node in find_all(roots, "relationship"):
        props = collect_properties(rel_node.children)
        from_table, from_column = split_table_column(props.get("fromColumn", ""))
        to_table, to_column = split_table_column(props.get("toColumn", ""))

        # TMDL only writes toCardinality/crossFilteringBehavior/isActive when
        # they differ from the (many-to-one, single-direction, active)
        # default — their absence is itself the confirmed value, not a gap.
        cardinality = "MANY_TO_MANY" if props.get("toCardinality") == "many" else "MANY_TO_ONE"
        cross_filter = "BOTH" if "both" in props.get("crossFilteringBehavior", "").lower() else "SINGLE"
        is_active = props.get("isActive", "true").lower() != "false"

        relationships.append(
            PowerBIRelationship(
                id=new_id(),
                model_id=model_id,
                from_table=from_table,
                from_column=from_column,
                to_table=to_table,
                to_column=to_column,
                cardinality=cardinality,
                cross_filter_direction=cross_filter,
                is_active=is_active,
                status=Status.CONFIRMED if from_table and to_table else Status.REQUIRES_INPUT,
                provenance=prov(f"relationship[{rel_node.rest.strip()}]:line{rel_node.line_no}"),
            )
        )

    if auto_date_table_names:
        _assign_auto_date_display_names(tables, relationships, auto_date_table_names)

    return PowerBISemanticModel(
        id=model_id,
        project_id=project_id,
        name=model_name,
        tables=tables,
        relationships=relationships,
        status=Status.CONFIRMED,
        provenance=prov("model"),
    )


def _assign_auto_date_display_names(
    tables: list[PowerBITable], relationships: list[PowerBIRelationship], auto_date_table_names: set[str]
) -> None:
    """An auto-date table exists for exactly one column, discoverable from
    the relationship that joins it to that column (it's always the "one"
    side). Falls back to a generic label if no relationship claims it."""
    tables_by_name = {t.name: t for t in tables}
    for rel in relationships:
        if rel.to_table in auto_date_table_names:
            target = tables_by_name.get(rel.to_table)
            if target is not None and target.display_name is None:
                target.display_name = f"Date Table — {rel.from_table}.{rel.from_column}"
        elif rel.from_table in auto_date_table_names:
            target = tables_by_name.get(rel.from_table)
            if target is not None and target.display_name is None:
                target.display_name = f"Date Table — {rel.to_table}.{rel.to_column}"

    for name in auto_date_table_names:
        target = tables_by_name.get(name)
        if target is not None and target.display_name is None:
            target.display_name = "Date Table (auto-generated)"
