"""Maps a TMDL semantic-model script into the same canonical model the JSON
adapter produces (spec section 3: one canonical model, one adapter per
input format) — everything downstream (dependency resolution, DAX
classification, Gold design, SQL translation, Metric View YAML, wrapper
views) works unchanged regardless of which adapter populated the model.

Only `table`/`column`/`measure`/`relationship` are extracted. `hierarchy`,
`partition`, `variation`, and `annotation` blocks are recognized by the
parser but not mapped into the canonical model — none of them have a home
there yet, and skipping them is not data loss for anything we currently do
with the model.
"""
from __future__ import annotations

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
            # hierarchy / partition / annotation / variation: not part of the
            # canonical model yet — intentionally skipped.

        tables.append(
            PowerBITable(
                id=table_id,
                model_id=model_id,
                name=name,
                table_type="REGULAR",
                source_hint=None,
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
