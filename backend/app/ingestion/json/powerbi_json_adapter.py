"""Maps a Power BI semantic-model JSON payload into the canonical model.

Handles the shape from the spec's example:

    {"model": {"tables": [{"name", "columns": [...], "measures": [...]}],
               "relationships": [...]}}

Every canonical field records the JSON path it came from so the UI/tests can
trace any value back to its source (spec section 32, Provenance).
"""
from __future__ import annotations

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


def extract_semantic_model(
    payload: dict, *, source_file: str, project_id: str, model_name: str
) -> PowerBISemanticModel:
    model_json = payload.get("model", {})
    model_id = new_id()

    def prov(json_path: str) -> Provenance:
        return Provenance(source_file=source_file, source_type="json", json_path=json_path)

    tables: list[PowerBITable] = []
    table_id_by_name: dict[str, str] = {}

    for i, table_json in enumerate(model_json.get("tables", [])):
        table_path = f"$.model.tables[{i}]"
        table_id = new_id()
        name = table_json.get("name")
        if not name:
            name = f"UnnamedTable{i}"
        table_id_by_name[name] = table_id

        columns = []
        for j, col_json in enumerate(table_json.get("columns", [])):
            col_path = f"{table_path}.columns[{j}]"
            col_name = col_json.get("name") or f"UnnamedColumn{j}"
            columns.append(
                PowerBIColumn(
                    id=new_id(),
                    table_id=table_id,
                    name=col_name,
                    data_type=col_json.get("dataType"),
                    is_calculated="expression" in col_json,
                    expression=col_json.get("expression"),
                    hidden=bool(col_json.get("isHidden", False)),
                    status=Status.CONFIRMED,
                    provenance=prov(col_path),
                )
            )

        measures = []
        for k, measure_json in enumerate(table_json.get("measures", [])):
            measure_path = f"{table_path}.measures[{k}]"
            measure_name = measure_json.get("name") or f"UnnamedMeasure{k}"
            expression = measure_json.get("expression", "")
            measures.append(
                PowerBIMeasure(
                    id=new_id(),
                    table_id=table_id,
                    name=measure_name,
                    expression=expression,
                    status=Status.CONFIRMED if expression else Status.REQUIRES_INPUT,
                    provenance=prov(measure_path),
                )
            )

        tables.append(
            PowerBITable(
                id=table_id,
                model_id=model_id,
                name=name,
                table_type=table_json.get("tableType", "REGULAR"),
                source_hint=table_json.get("source"),
                columns=columns,
                measures=measures,
                status=Status.CONFIRMED,
                provenance=prov(table_path),
            )
        )

    relationships: list[PowerBIRelationship] = []
    for i, rel_json in enumerate(model_json.get("relationships", [])):
        rel_path = f"$.model.relationships[{i}]"
        relationships.append(
            PowerBIRelationship(
                id=new_id(),
                model_id=model_id,
                from_table=rel_json.get("fromTable", ""),
                from_column=rel_json.get("fromColumn", ""),
                to_table=rel_json.get("toTable", ""),
                to_column=rel_json.get("toColumn", ""),
                cardinality=rel_json.get("cardinality", "REQUIRES_INPUT"),
                cross_filter_direction=rel_json.get("crossFilteringBehavior", "REQUIRES_INPUT"),
                is_active=bool(rel_json.get("isActive", True)),
                status=Status.CONFIRMED
                if rel_json.get("fromTable") and rel_json.get("toTable")
                else Status.REQUIRES_INPUT,
                provenance=prov(rel_path),
            )
        )

    return PowerBISemanticModel(
        id=model_id,
        project_id=project_id,
        name=model_name,
        tables=tables,
        relationships=relationships,
        status=Status.CONFIRMED,
        provenance=prov("$.model"),
    )
