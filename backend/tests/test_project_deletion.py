from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_delete_project_removes_it(db_session):
    project_id = client.post("/api/projects", json={"name": "To Delete"}).json()["id"]
    assert client.get(f"/api/projects/{project_id}").status_code == 200

    resp = client.delete(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 1}

    assert client.get(f"/api/projects/{project_id}").status_code == 404


def test_delete_unknown_project_404s(db_session):
    resp = client.delete("/api/projects/does-not-exist")
    assert resp.status_code == 404


def test_delete_all_projects_clears_everything(db_session):
    ids = [client.post("/api/projects", json={"name": f"P{i}"}).json()["id"] for i in range(3)]
    assert len(client.get("/api/projects").json()) == 3

    resp = client.delete("/api/projects")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 3}

    assert client.get("/api/projects").json() == []
    for pid in ids:
        assert client.get(f"/api/projects/{pid}").status_code == 404


def test_delete_all_on_empty_project_list_returns_zero(db_session):
    resp = client.delete("/api/projects")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 0}
