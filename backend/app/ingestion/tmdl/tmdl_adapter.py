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


def extract_semantic_model_from_tmdl(
    raw_text: str, *, source_file: str, project_id: str, model_name: str
) -> PowerBISemanticModel:
    roots = parse_tmdl(raw_text)
    model_id = new_id()

    def prov(locator: str) -> Provenance:
        return Provenance(source_file=source_file, source_type="tmdl", json_path=locator)

    tables: list[PowerBITable] = []

    for table_node in find_all(roots, "table"):
        name, _ = parse_name_and_expression(table_node.rest)
        table_id = new_id()
        table_locator = f"table[{name}]:line{table_node.line_no}"

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

    return PowerBISemanticModel(
        id=model_id,
        project_id=project_id,
        name=model_name,
        tables=tables,
        relationships=relationships,
        status=Status.CONFIRMED,
        provenance=prov("model"),
    )
