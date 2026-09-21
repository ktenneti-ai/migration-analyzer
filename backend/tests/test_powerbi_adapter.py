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
