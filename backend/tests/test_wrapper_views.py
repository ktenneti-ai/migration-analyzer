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
from app.parsers.dax.classifier import classify_measures
from app.parsers.dax.dependency_parser import resolve_dependencies
from app.recommendations.wrapper_views import build_wrapper_views


def _prov():
    return Provenance(source_file="x.json", source_type="json", json_path="$")


def test_finance_model_wraps_revenue_ytd(sample_data_dir):
    with open(os.path.join(sample_data_dir, "finance_model.json")) as f:
        raw = f.read()
    detection = detect(raw)
    model = extract_semantic_model(detection.payload, source_file="finance_model.json", project_id="p1", model_name="Finance")
    resolve_dependencies(model)
    classify_measures(model)

    specs = build_wrapper_views(model)
    assert len(specs) == 1
    spec = specs[0]
    assert spec.fact_table == "FactSales"
    assert spec.date_dimension == "DimDate"

    wrapped_names = {w.name for w in spec.wrapped_measures}
    assert wrapped_names == {"Revenue YTD"}
    w = spec.wrapped_measures[0]
    assert w.pattern == "to_date"
    assert w.sub_type == "ytd"
    assert w.base_measure == "Total Revenue"
    assert "PARTITION BY dim_date.year" in w.sql_column
    assert "ORDER BY dim_date.date" in w.sql_column

    assert "CREATE OR REPLACE VIEW fact_sales_wrapper AS" in spec.sql
    assert "MEASURE(`Total Revenue`) AS `Total Revenue`" in spec.sql
    assert "FROM metric_view_fact_sales" in spec.sql
    assert "GROUP BY dim_date.date, dim_date.year" in spec.sql

    # The other excluded measure has no recognized wrapper pattern, so it's
    # neither wrapped nor listed as skipped — it's already explained by the
    # classifier's own reasons (see the DAX Analysis report section).
    assert spec.skipped_measures == []


def _model_with_time_intel_but_no_date_dim() -> PowerBISemanticModel:
    table = PowerBITable(
        id="t1",
        model_id="m1",
        name="Fact",
        columns=[PowerBIColumn(id="c1", table_id="t1", name="Value", provenance=_prov())],
        measures=[
            PowerBIMeasure(id="me1", table_id="t1", name="Total", expression="SUM(Fact[Value])", provenance=_prov()),
            PowerBIMeasure(
                id="me2",
                table_id="t1",
                name="Total LY",
                expression="SAMEPERIODLASTYEAR([Total])",
                provenance=_prov(),
            ),
        ],
        provenance=_prov(),
    )
    return PowerBISemanticModel(id="m1", project_id="p1", name="Test", tables=[table], provenance=_prov())


def test_missing_date_dimension_is_reported_as_skipped_not_fabricated():
    model = _model_with_time_intel_but_no_date_dim()
    resolve_dependencies(model)
    classify_measures(model)

    specs = build_wrapper_views(model)
    assert len(specs) == 1
    spec = specs[0]
    assert spec.date_dimension is None
    assert spec.wrapped_measures == []
    assert len(spec.skipped_measures) == 1
    skipped = spec.skipped_measures[0]
    assert skipped.name == "Total LY"
    assert skipped.pattern == "prior_period"
    assert "date dimension" in skipped.reason


def test_no_facts_yields_no_wrapper_specs():
    model = PowerBISemanticModel(id="m1", project_id="p1", name="Empty", tables=[], provenance=_prov())
    assert build_wrapper_views(model) == []


def test_rank_pattern_wraps_without_a_date_dimension():
    table = PowerBITable(
        id="t1",
        model_id="m1",
        name="Fact",
        columns=[PowerBIColumn(id="c1", table_id="t1", name="Value", provenance=_prov())],
        measures=[
            PowerBIMeasure(id="me1", table_id="t1", name="Total", expression="SUM(Fact[Value])", provenance=_prov()),
            PowerBIMeasure(
                id="me2", table_id="t1", name="Rank", expression="RANKX(ALL(Fact), [Total])", provenance=_prov()
            ),
        ],
        provenance=_prov(),
    )
    model = PowerBISemanticModel(id="m1", project_id="p1", name="Test", tables=[table], provenance=_prov())
    resolve_dependencies(model)
    classify_measures(model)

    specs = build_wrapper_views(model)
    assert len(specs) == 1
    spec = specs[0]
    assert spec.date_dimension is None
    wrapped = {w.name: w for w in spec.wrapped_measures}
    assert "Rank" in wrapped
    assert wrapped["Rank"].pattern == "rank"
    assert "DENSE_RANK()" in wrapped["Rank"].sql_column
    assert "GROUP BY ALL;" in spec.sql


def test_gold_endpoint_includes_wrapper_views(db_session, sample_data_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Wrapper Test"}).json()["id"]
    path = os.path.join(sample_data_dir, "finance_model.json")
    with open(path, "rb") as f:
        client.post(
            f"/api/projects/{project_id}/ingest",
            files={"file": ("finance_model.json", f, "application/json")},
        )

    resp = client.get(f"/api/projects/{project_id}/gold")
    body = resp.json()
    assert len(body["wrapper_views"]) == 1
    assert body["wrapper_views"][0]["fact_table"] == "FactSales"

    export_resp = client.get(f"/api/projects/{project_id}/gold/wrapper-view/FactSales/export")
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"] == "application/sql"
    assert b"CREATE OR REPLACE VIEW fact_sales_wrapper" in export_resp.content


def test_export_unknown_fact_table_404s(db_session, sample_data_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Wrapper 404"}).json()["id"]
    path = os.path.join(sample_data_dir, "finance_model.json")
    with open(path, "rb") as f:
        client.post(
            f"/api/projects/{project_id}/ingest",
            files={"file": ("finance_model.json", f, "application/json")},
        )
    resp = client.get(f"/api/projects/{project_id}/gold/wrapper-view/NoSuchTable/export")
    assert resp.status_code == 404
