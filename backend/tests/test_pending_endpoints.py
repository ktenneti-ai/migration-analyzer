from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_sql_conversion_pending_shape(db_session):
    project_id = client.post("/api/projects", json={"name": "SQL Pending"}).json()["id"]
    resp = client.get(f"/api/projects/{project_id}/sql-conversion")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending"] is True
    assert body["items"] == []
    assert "reason" in body


def test_gold_pending_shape(db_session):
    project_id = client.post("/api/projects", json={"name": "Gold Pending"}).json()["id"]
    resp = client.get(f"/api/projects/{project_id}/gold")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending"] is True
    assert body["facts"] == []
    assert body["dimensions"] == []


def test_pending_endpoints_404_for_unknown_project(db_session):
    assert client.get("/api/projects/nope/sql-conversion").status_code == 404
    assert client.get("/api/projects/nope/gold").status_code == 404
