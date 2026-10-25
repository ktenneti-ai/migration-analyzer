"""Maps a Power BI semantic-model JSON payload into the canonical model.

Handles the shape from the spec's example:

    {"model": {"tables": [{"name", "columns": [...], "measures": [...]}],
               "relationships": [...]}}

Every canonical field records the JSON path it came from so the UI/tests can
trace any value back to its source (spec section 32, Provenance).
"""
from __future__ import annotations

from app.ingestion.tabular import (
    cross_filter_direction,
    m_parameter_value,
    relationship_cardinality,
    teradata_source_hint,
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


def _expression_text(value) -> str | None:
    """Real model.bim / TMSL exports store any multi-line expression as a
    list of lines (Tabular Editor and SSMS both write it that way); a
    single-line one is a plain string."""
    if isinstance(value, list):
        return "\n".join(str(line) for line in value)
    return value


def _m_parameters(model_json: dict) -> dict[str, str]:
    """Name -> literal value of every M parameter (model.expressions)."""
    params: dict[str, str] = {}
    for expr_json in model_json.get("expressions", []) or []:
        value = m_parameter_value(_expression_text(expr_json.get("expression")))
        if value is not None and expr_json.get("name"):
            params[expr_json["name"]] = value
    return params


def _source_hint(table_json: dict, parameters: dict[str, str]) -> str | None:
    """An explicit `source` hint if the export has one, else the Teradata
    object named in a partition's M query (how a real model.bim records
    where a table's data comes from)."""
    if table_json.get("source"):
        return table_json["source"]
    for partition in table_json.get("partitions", []) or []:
        source = partition.get("source") or {}
        if source.get("type", "m") != "m":
            continue
        hint = teradata_source_hint(_expression_text(source.get("expression")) or "", parameters)
        if hint is not None:
            return hint
    return None


def extract_semantic_model(
    payload: dict, *, source_file: str, project_id: str, model_name: str
) -> PowerBISemanticModel:
    model_json = payload.get("model", {})
    model_id = new_id()

    def prov(json_path: str) -> Provenance:
        return Provenance(source_file=source_file, source_type="json", json_path=json_path)

    tables: list[PowerBITable] = []
    table_id_by_name: dict[str, str] = {}
    parameters = _m_parameters(model_json)

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
                    expression=_expression_text(col_json.get("expression")),
                    hidden=bool(col_json.get("isHidden", False)),
                    status=Status.CONFIRMED,
                    provenance=prov(col_path),
                )
            )

        measures = []
        for k, measure_json in enumerate(table_json.get("measures", [])):
            measure_path = f"{table_path}.measures[{k}]"
            measure_name = measure_json.get("name") or f"UnnamedMeasure{k}"
            expression = _expression_text(measure_json.get("expression")) or ""
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
                source_hint=_source_hint(table_json, parameters),
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
                # A real model.bim records cardinality as fromCardinality /
                # toCardinality, written only when not the many-to-one
                # default; a simplified export may carry a single
                # `cardinality` value instead, which is kept as given.
                cardinality=rel_json.get("cardinality")
                or relationship_cardinality(rel_json.get("fromCardinality"), rel_json.get("toCardinality")),
                cross_filter_direction=cross_filter_direction(rel_json.get("crossFilteringBehavior")),
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
