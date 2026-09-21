import os

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _ingest_finance_model(sample_data_dir):
    project_id = client.post("/api/projects", json={"name": "Report Test"}).json()["id"]
    path = os.path.join(sample_data_dir, "finance_model.json")
    with open(path, "rb") as f:
        client.post(
            f"/api/projects/{project_id}/ingest",
            files={"file": ("finance_model.json", f, "application/json")},
        )
    return project_id


def test_report_has_real_and_deferred_sections(db_session, sample_data_dir):
    project_id = _ingest_finance_model(sample_data_dir)
    report = client.get(f"/api/projects/{project_id}/report").json()

    assert report["project_name"] == "Report Test"
    assert report["executive_summary"]["tables"] == 4
    assert report["executive_summary"]["migration_gaps"] == 2

    sections_by_key = {s["key"]: s for s in report["sections"]}
    assert sections_by_key["powerbi_inventory"]["status"] == "CONFIRMED"
    assert sections_by_key["migration_gaps"]["status"] == "CONFIRMED"
    assert len(sections_by_key["migration_gaps"]["details"]) == 2

    # Sections that need ingestion/engines that don't exist yet are explicit
    # placeholders, not silently omitted.
    assert sections_by_key["teradata_inventory"]["status"] == "REQUIRES_INPUT"
    assert "not yet implemented" in sections_by_key["teradata_inventory"]["summary"]


def test_report_on_empty_project_marks_sections_requires_input(db_session):
    project_id = client.post("/api/projects", json={"name": "Empty"}).json()["id"]
    report = client.get(f"/api/projects/{project_id}/report").json()
    sections_by_key = {s["key"]: s for s in report["sections"]}
    assert sections_by_key["powerbi_inventory"]["status"] == "REQUIRES_INPUT"
    assert sections_by_key["migration_scope"]["status"] == "REQUIRES_INPUT"


def test_cross_report_section_detects_shared_tables(db_session, sample_data_dir):
    project_id = client.post("/api/projects", json={"name": "Cross Report"}).json()["id"]
    path = os.path.join(sample_data_dir, "finance_model.json")
    # Same content ingested under two distinct model names, so the shared-table
    # detection (which keys on semantic model name) has two models to compare.
    for upload_filename in ["finance_model.json", "finance_model_v2.json"]:
        with open(path, "rb") as f:
            client.post(
                f"/api/projects/{project_id}/ingest",
                files={"file": (upload_filename, f, "application/json")},
            )
    report = client.get(f"/api/projects/{project_id}/report").json()
    cross = next(s for s in report["sections"] if s["key"] == "cross_report_analysis")
    assert cross["status"] == "INFERRED"
    assert len(cross["details"]) == 4  # FactSales, DimCustomer, DimProduct, DimDate all shared


def test_export_pdf_and_docx(db_session, sample_data_dir):
    project_id = _ingest_finance_model(sample_data_dir)

    pdf_resp = client.get(f"/api/projects/{project_id}/report/export", params={"format": "pdf"})
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF")

    docx_resp = client.get(f"/api/projects/{project_id}/report/export", params={"format": "docx"})
    assert docx_resp.status_code == 200
    assert docx_resp.content[:2] == b"PK"  # docx is a zip archive


def test_export_rejects_unknown_format(db_session, sample_data_dir):
    project_id = _ingest_finance_model(sample_data_dir)
    resp = client.get(f"/api/projects/{project_id}/report/export", params={"format": "txt"})
    assert resp.status_code == 422
