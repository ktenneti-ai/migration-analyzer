import os

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_plan_has_nine_phases_and_reflects_ingestion_state(db_session, sample_data_dir):
    project_id = client.post("/api/projects", json={"name": "Plan Test"}).json()["id"]

    empty_plan = client.get(f"/api/projects/{project_id}/migration-plan").json()
    assert len(empty_plan) == 9
    discovery = next(p for p in empty_plan if p["key"] == "discovery")
    assert discovery["status"] == "REQUIRES_INPUT"
    assert discovery["blocked_reason"] is not None

    teradata_phase = next(p for p in empty_plan if p["key"] == "teradata_assessment")
    assert teradata_phase["status"] == "REQUIRES_INPUT"
    assert "Teradata" in teradata_phase["blocked_reason"]

    path = os.path.join(sample_data_dir, "finance_model.json")
    with open(path, "rb") as f:
        client.post(
            f"/api/projects/{project_id}/ingest",
            files={"file": ("finance_model.json", f, "application/json")},
        )

    plan_after_ingest = client.get(f"/api/projects/{project_id}/migration-plan").json()
    discovery_after = next(p for p in plan_after_ingest if p["key"] == "discovery")
    assert discovery_after["status"] == "CONFIRMED"
    assert discovery_after["blocked_reason"] is None

    # Later phases still can't proceed without Teradata/Databricks input.
    gold_after = next(p for p in plan_after_ingest if p["key"] == "gold")
    assert gold_after["status"] == "REQUIRES_INPUT"


def test_plan_unknown_project_404(db_session):
    resp = client.get("/api/projects/does-not-exist/migration-plan")
    assert resp.status_code == 404
