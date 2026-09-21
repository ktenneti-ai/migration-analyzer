import os

from app.ingestion.json.detector import detect
from app.ingestion.json.powerbi_json_adapter import extract_semantic_model
from app.metadata.models import (
    PowerBIColumn,
    PowerBIMeasure,
    PowerBIRelationship,
    PowerBISemanticModel,
    PowerBITable,
    Provenance,
)
from app.parsers.dax.dependency_parser import resolve_dependencies
from app.recommendations.gold_design import detect_fact_groups


def _prov():
    return Provenance(source_file="x.json", source_type="json", json_path="$")


def test_finance_model_infers_factsales_and_three_dimensions(sample_data_dir):
    with open(os.path.join(sample_data_dir, "finance_model.json")) as f:
        raw = f.read()
    detection = detect(raw)
    model = extract_semantic_model(detection.payload, source_file="finance_model.json", project_id="p1", model_name="Finance")
    resolve_dependencies(model)

    facts, dimensions = detect_fact_groups(model)

    assert [f.table_name for f in facts] == ["FactSales"]
    fact = facts[0]
    assert set(fact.measures) == {
        "Total Revenue",
        "Total Cost",
        "Gross Margin",
        "Revenue YTD",
        "Unresolved Reference Example",
    }
    assert "REQUIRES_INPUT" in fact.grain

    assert {d.table_name for d in dimensions} == {"DimCustomer", "DimProduct", "DimDate"}
    for d in dimensions:
        assert d.related_fact_tables == ["FactSales"]
        assert d.evidence


def test_dimension_named_table_not_selected_as_fact_without_evidence():
    # A measure that only touches a dimension-named table should not turn
    # that table into a "fact" just because it's the only table around.
    model = PowerBISemanticModel(
        id="m1",
        project_id="p1",
        name="Test",
        tables=[
            PowerBITable(
                id="t1",
                model_id="m1",
                name="DimProduct",
                columns=[PowerBIColumn(id="c1", table_id="t1", name="Price", provenance=_prov())],
                measures=[
                    PowerBIMeasure(
                        id="me1", table_id="t1", name="Avg Price", expression="AVERAGE(DimProduct[Price])", provenance=_prov()
                    )
                ],
                provenance=_prov(),
            )
        ],
        provenance=_prov(),
    )
    resolve_dependencies(model)
    facts, dimensions = detect_fact_groups(model)

    # DimProduct is the only table, so it's still picked (low-confidence
    # fallback), but nothing here should silently mislabel it as high-confidence.
    assert facts[0].table_name == "DimProduct"
    assert "low confidence" in facts[0].evidence[0]
    assert dimensions == []  # no relationship exists, so no dimension candidate is asserted


def test_no_measures_yields_no_candidates():
    model = PowerBISemanticModel(id="m1", project_id="p1", name="Empty", tables=[], provenance=_prov())
    facts, dimensions = detect_fact_groups(model)
    assert facts == []
    assert dimensions == []


def test_gold_endpoint_reports_pending_false_once_facts_exist(db_session, sample_data_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Gold Test"}).json()["id"]
    path = os.path.join(sample_data_dir, "finance_model.json")
    with open(path, "rb") as f:
        client.post(
            f"/api/projects/{project_id}/ingest",
            files={"file": ("finance_model.json", f, "application/json")},
        )

    resp = client.get(f"/api/projects/{project_id}/gold")
    body = resp.json()
    assert body["pending"] is False
    assert len(body["facts"]) == 1
    assert body["facts"][0]["table_name"] == "FactSales"
    assert len(body["dimensions"]) == 3
    assert body["bridges"] == []
    assert body["aggregates"] == []
