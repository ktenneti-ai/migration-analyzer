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
    assert rows[0]["teradata_object_type"] == "VIEW"
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


def test_dashboard_counts_agree_with_the_teradata_routes(db_session):
    # Dashboard.tsx and the Teradata Assessment page both surface these
    # counts — they must come from the same computation or the two pages
    # could silently disagree.
    project_id, client = _ingest(db_session)
    dashboard = client.get(f"/api/projects/{project_id}/dashboard").json()
    referenced = client.get(f"/api/projects/{project_id}/teradata/referenced-objects").json()
    unresolved = client.get(f"/api/projects/{project_id}/teradata/unresolved-tables").json()

    assert dashboard["teradata_referenced_objects"] == len(referenced) == 1
    assert dashboard["teradata_unresolved_objects"] == len(unresolved) == 1
    assert dashboard["teradata_views"] == 1  # V_CPED_RUN_DATES -> "V_" naming convention
    assert dashboard["teradata_base_tables"] == 0


def test_teradata_object_without_the_v_prefix_is_classified_as_a_base_table(db_session):
    raw = (
        "createOrReplace\n"
        "\tmodel Model\n"
        "\t\ttable STAGING\n"
        "\t\t\tcolumn Id\n"
        "\t\t\t\tdataType: int64\n"
        "\n"
        "\t\t\tpartition STAGING = m\n"
        "\t\t\t\tmode: import\n"
        "\t\t\t\tsource =\n"
        "\t\t\t\t\t\tlet\n"
        '\t\t\t\t\t\t    Source = Teradata.Database("BNRPROD", [HierarchicalNavigation=true]),\n'
        '\t\t\t\t\t\t    CP_ED = Source{[Schema="CP_ED"]}[Data],\n'
        '\t\t\t\t\t\t    STAGING_TBL1 = CP_ED{[Name="STAGING_TBL"]}[Data]\n'
        "\t\t\t\t\t\tin\n"
        "\t\t\t\t\t\t    STAGING_TBL1\n"
    )
    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Base Table Test"}).json()["id"]
    client.post(
        f"/api/projects/{project_id}/ingest",
        files={"file": ("y.tmdl", raw.encode(), "application/octet-stream")},
    )
    rows = client.get(f"/api/projects/{project_id}/teradata/referenced-objects").json()
    assert rows[0]["teradata_object_type"] == "BASE_TABLE"

    dashboard = client.get(f"/api/projects/{project_id}/dashboard").json()
    assert dashboard["teradata_base_tables"] == 1
    assert dashboard["teradata_views"] == 0
