import os

import yaml

from app.ingestion.json.detector import detect
from app.ingestion.json.powerbi_json_adapter import extract_semantic_model
from app.metadata.models import PowerBIColumn, PowerBIMeasure, PowerBISemanticModel, PowerBITable, Provenance
from app.parsers.dax.classifier import classify_measures
from app.parsers.dax.dependency_parser import resolve_dependencies
from app.recommendations.metric_view_yaml import build_metric_view_specs, render_yaml


def _prov():
    return Provenance(source_file="x.json", source_type="json", json_path="$")


def test_finance_model_generates_a_valid_metric_view_spec(sample_data_dir):
    with open(os.path.join(sample_data_dir, "finance_model.json")) as f:
        raw = f.read()
    detection = detect(raw)
    model = extract_semantic_model(detection.payload, source_file="finance_model.json", project_id="p1", model_name="Finance")
    resolve_dependencies(model)
    classify_measures(model)

    specs = build_metric_view_specs(model)
    assert len(specs) == 1
    spec = specs[0]
    assert spec.fact_table == "FactSales"
    assert spec.source == "fact_sales"

    measure_names = {m.name for m in spec.measures}
    # Total Revenue / Total Cost / Gross Margin are AUTO; Revenue YTD is
    # MANUAL_PORT (excluded); the deliberately-broken measure is needs_review
    # (excluded) — see test_sql_translator.py for the underlying statuses.
    assert measure_names == {"Total Revenue", "Total Cost", "Gross Margin"}
    excluded_names = {e.name for e in spec.excluded_measures}
    assert "Revenue YTD" in excluded_names
    assert "Unresolved Reference Example" in excluded_names

    # Joins: FactSales -> DimCustomer/DimProduct/DimDate.
    join_sources = {j.source for j in spec.joins}
    assert join_sources == {"dim_customer", "dim_product", "dim_date"}

    # Every measure must carry its DAX provenance comment (a spec requirement).
    for m in spec.measures:
        assert m.expr.startswith("-- DAX:")

    rendered = render_yaml(spec)
    parsed = yaml.safe_load(rendered)
    assert parsed["version"] == "1.1"
    assert parsed["source"] == "fact_sales"
    assert len(parsed["measures"]) == 3
    assert len(parsed["joins"]) == 3


def test_selectedvalue_measure_is_excluded_as_visual_layer_pattern():
    table = PowerBITable(
        id="t1",
        model_id="m1",
        name="Fact",
        columns=[PowerBIColumn(id="c1", table_id="t1", name="Region", provenance=_prov())],
        measures=[
            PowerBIMeasure(
                id="me1", table_id="t1", name="Selected Region", expression="SELECTEDVALUE(Fact[Region])", provenance=_prov()
            )
        ],
        provenance=_prov(),
    )
    model = PowerBISemanticModel(id="m1", project_id="p1", name="Test", tables=[table], provenance=_prov())
    resolve_dependencies(model)
    classify_measures(model)

    specs = build_metric_view_specs(model)
    # No usable measures survive -> no spec emitted for this fact at all.
    assert specs == []


def test_no_facts_yields_no_specs():
    model = PowerBISemanticModel(id="m1", project_id="p1", name="Empty", tables=[], provenance=_prov())
    assert build_metric_view_specs(model) == []


def test_gold_endpoint_includes_rendered_yaml(db_session, sample_data_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Metric View Test"}).json()["id"]
    path = os.path.join(sample_data_dir, "finance_model.json")
    with open(path, "rb") as f:
        client.post(
            f"/api/projects/{project_id}/ingest",
            files={"file": ("finance_model.json", f, "application/json")},
        )

    resp = client.get(f"/api/projects/{project_id}/gold")
    body = resp.json()
    assert len(body["metric_views"]) == 1
    mv = body["metric_views"][0]
    assert mv["fact_table"] == "FactSales"
    parsed = yaml.safe_load(mv["yaml"])
    assert parsed["version"] == "1.1"
    assert parsed["source"] == "fact_sales"

    export_resp = client.get(f"/api/projects/{project_id}/gold/metric-view/FactSales/export")
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"] == "application/x-yaml"
    assert b"source: fact_sales" in export_resp.content


def test_export_unknown_fact_table_404s(db_session, sample_data_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Metric View 404"}).json()["id"]
    path = os.path.join(sample_data_dir, "finance_model.json")
    with open(path, "rb") as f:
        client.post(
            f"/api/projects/{project_id}/ingest",
            files={"file": ("finance_model.json", f, "application/json")},
        )
    resp = client.get(f"/api/projects/{project_id}/gold/metric-view/NoSuchTable/export")
    assert resp.status_code == 404
