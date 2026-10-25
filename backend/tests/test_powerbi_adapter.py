import json
import os

from app.ingestion.json.detector import detect
from app.ingestion.json.powerbi_json_adapter import extract_semantic_model
from app.metadata.models import Status


def _load_finance_model(sample_data_dir):
    path = os.path.join(sample_data_dir, "finance_model.json")
    with open(path) as f:
        return f.read()


def test_extracts_tables_columns_measures_relationships(sample_data_dir):
    raw = _load_finance_model(sample_data_dir)
    detection = detect(raw)
    model = extract_semantic_model(
        detection.payload, source_file="finance_model.json", project_id="p1", model_name="Finance"
    )

    assert {t.name for t in model.tables} == {"FactSales", "DimCustomer", "DimProduct", "DimDate"}

    fact_sales = next(t for t in model.tables if t.name == "FactSales")
    assert len(fact_sales.columns) == 5
    assert len(fact_sales.measures) == 5
    assert fact_sales.status == Status.CONFIRMED

    total_revenue = next(m for m in fact_sales.measures if m.name == "Total Revenue")
    assert total_revenue.expression == "SUM(FactSales[Revenue])"
    assert total_revenue.provenance.json_path.startswith("$.model.tables[")
    assert total_revenue.provenance.source_file == "finance_model.json"

    assert len(model.relationships) == 3
    rel = model.relationships[0]
    assert rel.from_table == "FactSales"
    assert rel.status == Status.CONFIRMED


def test_missing_relationship_fields_flagged_requires_input():
    payload = {
        "model": {
            "tables": [],
            "relationships": [{"fromColumn": "X"}],  # missing fromTable/toTable
        }
    }
    model = extract_semantic_model(
        payload, source_file="x.json", project_id="p1", model_name="X"
    )
    assert model.relationships[0].status == Status.REQUIRES_INPUT


def test_multiline_expressions_stored_as_line_lists_are_joined():
    # model.bim writes any multi-line expression as a list of lines.
    payload = {
        "model": {
            "tables": [
                {
                    "name": "Fact",
                    "columns": [
                        {"name": "Amt", "dataType": "decimal"},
                        {"name": "Flag", "type": "calculated", "expression": ["IF(", "  Fact[Amt] > 0, 1, 0)"]},
                    ],
                    "measures": [{"name": "YTD", "expression": ["", "VAR x = SUM(Fact[Amt])", "RETURN x"]}],
                }
            ]
        }
    }
    model = extract_semantic_model(payload, source_file="m.bim", project_id="p1", model_name="M")
    table = model.tables[0]
    assert table.measures[0].expression == "\nVAR x = SUM(Fact[Amt])\nRETURN x"
    assert table.measures[0].status == Status.CONFIRMED
    assert table.columns[1].expression == "IF(\n  Fact[Amt] > 0, 1, 0)"
    assert table.columns[1].is_calculated


def test_bim_relationship_cardinality_and_cross_filter():
    # model.bim writes fromCardinality/toCardinality and crossFilteringBehavior
    # only when they differ from the many-to-one, one-direction default.
    payload = {
        "model": {
            "tables": [{"name": "A"}, {"name": "B"}],
            "relationships": [
                {"fromTable": "A", "fromColumn": "k", "toTable": "B", "toColumn": "k"},
                {"fromTable": "A", "fromColumn": "k", "toTable": "B", "toColumn": "k",
                 "fromCardinality": "many", "toCardinality": "many", "crossFilteringBehavior": "bothDirections"},
                {"fromTable": "A", "fromColumn": "k", "toTable": "B", "toColumn": "k", "fromCardinality": "one"},
                {"fromTable": "A", "fromColumn": "k", "toTable": "B", "toColumn": "k",
                 "cardinality": "MANY_TO_ONE", "crossFilteringBehavior": "BIDIRECTIONAL"},
            ],
        }
    }
    model = extract_semantic_model(payload, source_file="m.bim", project_id="p1", model_name="M")
    assert [(r.cardinality, r.cross_filter_direction) for r in model.relationships] == [
        ("MANY_TO_ONE", "SINGLE"),
        ("MANY_TO_MANY", "BOTH"),
        ("ONE_TO_ONE", "SINGLE"),
        ("MANY_TO_ONE", "BOTH"),
    ]


def test_bim_teradata_source_is_read_from_partition_m_query():
    payload = {
        "model": {
            "expressions": [
                {"name": "Server", "kind": "m",
                 "expression": '"tdprod" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'},
            ],
            "tables": [
                {
                    "name": "GL",
                    "partitions": [{"name": "GL", "source": {"type": "m", "expression": [
                        "let",
                        "    Source = Teradata.Database(Server, [HierarchicalNavigation=true]),",
                        '    FIN = Source{[Schema="EDW_FIN"]}[Data],',
                        '    V = FIN{[Name="V_GL_ENTRY"]}[Data]',
                        "in",
                        "    V",
                    ]}}],
                },
                {"name": "Calc", "partitions": [{"name": "Calc", "source": {
                    "type": "calculated", "expression": 'Teradata.Database("not a source")'}}]},
            ],
        }
    }
    model = extract_semantic_model(payload, source_file="m.bim", project_id="p1", model_name="M")
    hints = {t.name: t.source_hint for t in model.tables}
    assert hints == {"GL": "Teradata: tdprod.EDW_FIN.V_GL_ENTRY", "Calc": None}
