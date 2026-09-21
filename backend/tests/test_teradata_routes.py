from fastapi.testclient import TestClient

from app.main import app

_RAW = (
    "createOrReplace\n"
    "\tmodel Model\n"
    "\t\ttable RUN_DATES\n"
    "\t\t\tcolumn LAST_UPDATE_DTTM\n"
    "\t\t\t\tdataType: dateTime\n"
    "\n"
    "\t\t\tpartition RUN_DATES = m\n"
    "\t\t\t\tmode: import\n"
    "\t\t\t\tsource =\n"
    "\t\t\t\t\t\tlet\n"
    '\t\t\t\t\t\t    Source = Teradata.Database("BNRPROD", [HierarchicalNavigation=true]),\n'
    '\t\t\t\t\t\t    CP_ED = Source{[Schema="CP_ED"]}[Data],\n'
    '\t\t\t\t\t\t    V_CPED_RUN_DATES1 = CP_ED{[Name="V_CPED_RUN_DATES"]}[Data]\n'
    "\t\t\t\t\t\tin\n"
    "\t\t\t\t\t\t    V_CPED_RUN_DATES1\n"
    "\n"
    "\t\ttable DimCustomer\n"
    "\t\t\tcolumn CustomerKey\n"
    "\t\t\t\tdataType: int64\n"
    "\n"
    "\t\ttable LocalDateTable_75add05e-23ff-4231-8e2a-ecf332e78bf4\n"
    "\t\t\tisHidden\n"
    "\t\t\tcolumn Date\n"
    "\t\t\t\tdataType: dateTime\n"
    "\t\t\tannotation __PBI_LocalDateTable = true\n"
    "\n"
    "\t\trelationship r1\n"
    "\t\t\tfromColumn: RUN_DATES.LAST_UPDATE_DTTM\n"
    "\t\t\ttoColumn: LocalDateTable_75add05e-23ff-4231-8e2a-ecf332e78bf4.Date\n"
)


def _ingest(db_session) -> str:
    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Teradata Routes Test"}).json()["id"]
    resp = client.post(
        f"/api/projects/{project_id}/ingest",
        files={"file": ("x.tmdl", _RAW.encode(), "application/octet-stream")},
    )
    assert resp.status_code == 200
    return project_id, client


def test_referenced_objects_lists_only_real_teradata_backed_tables(db_session):
    project_id, client = _ingest(db_session)
    rows = client.get(f"/api/projects/{project_id}/teradata/referenced-objects").json()

    assert len(rows) == 1
    assert rows[0]["power_bi_table"] == "RUN_DATES"
    assert rows[0]["teradata_database"] == "BNRPROD"
    assert rows[0]["teradata_schema"] == "CP_ED"
    assert rows[0]["teradata_object"] == "V_CPED_RUN_DATES"
    assert rows[0]["model"] == "x"
    assert rows[0]["columns"] == 1
    assert rows[0]["measures"] == 0
    assert rows[0]["source_file"] == "x.tmdl"


def test_unresolved_tables_excludes_teradata_backed_and_system_tables(db_session):
    project_id, client = _ingest(db_session)
    rows = client.get(f"/api/projects/{project_id}/teradata/unresolved-tables").json()

    # DimCustomer has no partition at all -> unresolved. RUN_DATES is
    # resolved (excluded). The auto-date LocalDateTable is a system table,
    # not a real object needing a Teradata source -> also excluded.
    assert [r["power_bi_table"] for r in rows] == ["DimCustomer"]
    assert rows[0]["model"] == "x"
    assert rows[0]["columns"] == 1
    assert rows[0]["measures"] == 0
    assert rows[0]["source_file"] == "x.tmdl"
