import os

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _upload(project_id, sample_data_dir, filename):
    path = os.path.join(sample_data_dir, filename)
    with open(path, "rb") as f:
        return client.post(
            f"/api/projects/{project_id}/ingest",
            files={"file": (filename, f, "application/json")},
        )


def test_full_ingestion_round_trip(db_session, sample_data_dir):
    create_resp = client.post("/api/projects", json={"name": "Finance Migration"})
    assert create_resp.status_code == 200
    project_id = create_resp.json()["id"]

    ingest_resp = _upload(project_id, sample_data_dir, "finance_model.json")
    assert ingest_resp.status_code == 200
    body = ingest_resp.json()
    assert body["detected_schema"] == "power_bi_model"
    assert body["tables_extracted"] == 4
    assert body["measures_extracted"] == 5
    assert body["gaps_found"] == 2

    dashboard = client.get(f"/api/projects/{project_id}/dashboard").json()
    assert dashboard["tables"] == 4
    assert dashboard["measures"] == 5
    assert dashboard["relationships"] == 3
    assert dashboard["migration_gaps"] == 2

    tables = client.get(f"/api/projects/{project_id}/powerbi/tables").json()
    assert {t["name"] for t in tables} == {"FactSales", "DimCustomer", "DimProduct", "DimDate"}

    measures = client.get(f"/api/projects/{project_id}/powerbi/measures").json()
    gross_margin = next(m for m in measures if m["name"] == "Gross Margin")
    assert set(gross_margin["referenced_measures"]) == {"Total Revenue", "Total Cost"}

    relationships = client.get(f"/api/projects/{project_id}/powerbi/relationships").json()
    assert len(relationships) == 3

    gaps = client.get(f"/api/projects/{project_id}/gaps").json()
    assert len(gaps) == 2

    lineage = client.get(f"/api/projects/{project_id}/lineage").json()
    assert len(lineage["nodes"]) > 0
    assert len(lineage["edges"]) > 0


def test_multi_file_project_ingestion(db_session, sample_data_dir):
    create_resp = client.post("/api/projects", json={"name": "Multi-file Project"})
    project_id = create_resp.json()["id"]

    _upload(project_id, sample_data_dir, "finance_model.json")
    _upload(project_id, sample_data_dir, "operations_model.json")

    dashboard = client.get(f"/api/projects/{project_id}/dashboard").json()
    assert dashboard["semantic_models"] == 2
    assert dashboard["tables"] == 6  # 4 finance + 2 operations


def test_rejects_non_json_file(db_session, sample_data_dir):
    create_resp = client.post("/api/projects", json={"name": "Bad Upload"})
    project_id = create_resp.json()["id"]
    resp = client.post(
        f"/api/projects/{project_id}/ingest",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


def test_ingest_unknown_project_returns_400(db_session, sample_data_dir):
    resp = _upload("does-not-exist", sample_data_dir, "finance_model.json")
    assert resp.status_code == 400


def test_json_with_utf8_bom_is_accepted(db_session, sample_data_dir):
    # PowerShell/Tabular Editor exports on Windows commonly prepend a UTF-8
    # BOM; a naive .decode("utf-8") leaves ﻿ at position 0 and json.loads
    # fails with "Expecting value: line 1 column 1 (char 0)".
    project_id = client.post("/api/projects", json={"name": "BOM Test"}).json()["id"]
    path = os.path.join(sample_data_dir, "finance_model.json")
    with open(path, "rb") as f:
        content = b"\xef\xbb\xbf" + f.read()
    resp = client.post(
        f"/api/projects/{project_id}/ingest",
        files={"file": ("finance_model.json", content, "application/json")},
    )
    assert resp.status_code == 200
    assert resp.json()["tables_extracted"] == 4


def test_non_utf8_file_gives_a_clear_error(db_session, sample_data_dir):
    project_id = client.post("/api/projects", json={"name": "Bad Encoding"}).json()["id"]
    resp = client.post(
        f"/api/projects/{project_id}/ingest",
        files={"file": ("model.json", b"\xff\xfe\x00\x01binary garbage", "application/json")},
    )
    assert resp.status_code == 400
    assert "UTF-8" in resp.json()["detail"]


def test_teradata_json_is_accepted_but_not_extracted(db_session, sample_data_dir):
    create_resp = client.post("/api/projects", json={"name": "Teradata Only"})
    project_id = create_resp.json()["id"]
    resp = _upload(project_id, sample_data_dir, "teradata_sample.json")
    assert resp.status_code == 200
    assert resp.json()["detected_schema"] == "teradata"
    assert resp.json()["tables_extracted"] == 0

    project = client.get(f"/api/projects/{project_id}").json()
    assert project["source_artifacts"][0]["detected_schema"] == "teradata"
