import os

from app.ingestion.json.detector import DetectedSchema, detect
from app.ingestion.tmdl.parser import (
    collect_properties,
    find_all,
    parse_name_and_expression,
    parse_tmdl,
    split_table_column,
)
from app.ingestion.tmdl.tmdl_adapter import extract_semantic_model_from_tmdl
from app.metadata.models import Status
from app.parsers.dax.dependency_parser import resolve_dependencies


def _load_sample(sample_data_dir):
    with open(os.path.join(sample_data_dir, "finance_model.tmdl")) as f:
        return f.read()


def test_detector_recognizes_tmdl(sample_data_dir):
    raw = _load_sample(sample_data_dir)
    result = detect(raw)
    assert result.schema == DetectedSchema.TMDL


def test_parser_builds_expected_tree_shape(sample_data_dir):
    raw = _load_sample(sample_data_dir)
    roots = parse_tmdl(raw)
    tables = find_all(roots, "table")
    assert [parse_name_and_expression(t.rest)[0] for t in tables] == ["FactSales", "DimCustomer"]

    relationships = find_all(roots, "relationship")
    assert len(relationships) == 1


def test_multiline_fenced_expression_is_captured_as_one_string(sample_data_dir):
    raw = _load_sample(sample_data_dir)
    roots = parse_tmdl(raw)
    fact_sales = find_all(roots, "table")[0]
    measures = [c for c in fact_sales.children if c.keyword == "measure"]
    region_summary = next(m for m in measures if parse_name_and_expression(m.rest)[0] == "Region Summary")
    _, expr = parse_name_and_expression(region_summary.rest)
    assert expr == '"Revenue by region: " & [Total Revenue]'


def test_collect_properties_handles_flags_and_key_value():
    raw = "createOrReplace\n\ttable T\n\t\tcolumn C\n\t\t\tdataType: string\n\t\t\tisHidden\n"
    roots = parse_tmdl(raw)
    table = find_all(roots, "table")[0]
    column = find_all([table], "column")[0]
    props = collect_properties(column.children)
    assert props == {"dataType": "string", "isHidden": "true"}


def test_split_table_column_handles_quoted_and_bare_names():
    assert split_table_column("FactSales.CustomerKey") == ("FactSales", "CustomerKey")
    assert split_table_column("'Metrics by Hour'.METRIC_DATE") == ("Metrics by Hour", "METRIC_DATE")


def test_extract_semantic_model_from_tmdl_matches_json_adapter_shape(sample_data_dir):
    raw = _load_sample(sample_data_dir)
    model = extract_semantic_model_from_tmdl(raw, source_file="finance_model.tmdl", project_id="p1", model_name="Finance")

    assert {t.name for t in model.tables} == {"FactSales", "DimCustomer"}
    fact_sales = next(t for t in model.tables if t.name == "FactSales")
    assert {c.name for c in fact_sales.columns} == {"CustomerKey", "Revenue", "Cost"}
    assert len(fact_sales.measures) == 4
    assert fact_sales.status == Status.CONFIRMED

    total_revenue = next(m for m in fact_sales.measures if m.name == "Total Revenue")
    assert total_revenue.expression == "SUM(FactSales[Revenue])"
    assert total_revenue.provenance.source_type == "tmdl"
    assert "FactSales" in total_revenue.provenance.json_path

    gross_margin = next(m for m in fact_sales.measures if m.name == "Gross Margin")
    assert gross_margin.expression == "[Total Revenue] - [Total Cost]"

    assert len(model.relationships) == 1
    rel = model.relationships[0]
    assert rel.from_table == "FactSales"
    assert rel.from_column == "CustomerKey"
    assert rel.to_table == "DimCustomer"
    assert rel.to_column == "CustomerKey"
    assert rel.cardinality == "MANY_TO_ONE"
    assert rel.status == Status.CONFIRMED


def test_dependency_resolution_works_on_tmdl_extracted_model(sample_data_dir):
    raw = _load_sample(sample_data_dir)
    model = extract_semantic_model_from_tmdl(raw, source_file="finance_model.tmdl", project_id="p1", model_name="Finance")
    gaps = resolve_dependencies(model)

    fact_sales = next(t for t in model.tables if t.name == "FactSales")
    gross_margin = next(m for m in fact_sales.measures if m.name == "Gross Margin")
    assert set(gross_margin.referenced_measures) == {"Total Revenue", "Total Cost"}
    assert gaps == []


def test_relationship_cardinality_and_flags():
    raw = (
        "createOrReplace\n"
        "\tmodel Model\n"
        "\t\ttable A\n"
        "\t\ttable B\n"
        "\t\trelationship r1\n"
        "\t\t\ttoCardinality: many\n"
        "\t\t\tcrossFilteringBehavior: bothDirections\n"
        "\t\t\tisActive: false\n"
        "\t\t\tfromColumn: A.Key\n"
        "\t\t\ttoColumn: B.Key\n"
    )
    model = extract_semantic_model_from_tmdl(raw, source_file="x.tmdl", project_id="p1", model_name="X")
    rel = model.relationships[0]
    assert rel.cardinality == "MANY_TO_MANY"
    assert rel.cross_filter_direction == "BOTH"
    assert rel.is_active is False


def test_teradata_partition_source_is_captured_as_source_hint():
    # Real shape from a production TMDL export: an "m" partition whose query
    # names the exact upstream Teradata database/schema/view — not fenced
    # with ``` (unlike the DAX examples elsewhere in this file), so the
    # generic tokenizer splits each M step into its own child node.
    raw = (
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
    )
    model = extract_semantic_model_from_tmdl(raw, source_file="x.tmdl", project_id="p1", model_name="X")
    run_dates = next(t for t in model.tables if t.name == "RUN_DATES")
    assert run_dates.source_hint == "Teradata: BNRPROD.CP_ED.V_CPED_RUN_DATES"


def test_table_without_a_teradata_partition_has_no_source_hint():
    raw = (
        "createOrReplace\n"
        "\tmodel Model\n"
        "\t\ttable DimCustomer\n"
        "\t\t\tcolumn CustomerKey\n"
        "\t\t\t\tdataType: int64\n"
    )
    model = extract_semantic_model_from_tmdl(raw, source_file="x.tmdl", project_id="p1", model_name="X")
    assert model.tables[0].source_hint is None


def test_auto_date_table_gets_a_logical_display_name():
    # Power BI's Auto Date/Time feature generates one hidden calendar table
    # per date column, named with a GUID suffix — meaningless in an
    # inventory UI. The table should get a derived display_name from the
    # column it was built for, without changing its real `name` (which
    # relationships/joins/SQL generation key off).
    raw = (
        "createOrReplace\n"
        "\tmodel Model\n"
        "\t\ttable RUN_DATES\n"
        "\t\t\tcolumn LAST_UPDATE_DTTM\n"
        "\t\t\t\tdataType: dateTime\n"
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
    model = extract_semantic_model_from_tmdl(raw, source_file="x.tmdl", project_id="p1", model_name="X")

    run_dates = next(t for t in model.tables if t.name == "RUN_DATES")
    assert run_dates.display_name is None  # ordinary table — untouched

    date_table = next(t for t in model.tables if t.name.startswith("LocalDateTable_"))
    assert date_table.display_name == "Date Table — RUN_DATES.LAST_UPDATE_DTTM"
    # The real name is preserved — relationships still reference it exactly.
    assert model.relationships[0].to_table == date_table.name


def test_auto_date_table_without_a_relationship_gets_a_generic_label():
    raw = (
        "createOrReplace\n"
        "\tmodel Model\n"
        "\t\ttable DateTableTemplate_abc\n"
        "\t\t\tcolumn Date\n"
        "\t\t\t\tdataType: dateTime\n"
        "\t\t\tannotation __PBI_TemplateDateTable = true\n"
    )
    model = extract_semantic_model_from_tmdl(raw, source_file="x.tmdl", project_id="p1", model_name="X")
    assert model.tables[0].display_name == "Date Table (auto-generated)"


def test_dashboard_excludes_auto_date_tables_and_their_relationships(db_session):
    # Power BI Desktop's own model view never counts Auto Date/Time tables as
    # real tables — the assessment's dashboard should agree, so its counts
    # match what the user sees in Power BI itself (reported discrepancy: PBI
    # shows 11 tables/8 relationships, the assessment showed 27/23 before
    # this fix because it counted every auto-generated calendar table too).
    from fastapi.testclient import TestClient

    from app.main import app

    raw = (
        "createOrReplace\n"
        "\tmodel Model\n"
        "\t\ttable RUN_DATES\n"
        "\t\t\tcolumn LAST_UPDATE_DTTM\n"
        "\t\t\t\tdataType: dateTime\n"
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
        "\n"
        "\t\trelationship r2\n"
        "\t\t\tfromColumn: RUN_DATES.LAST_UPDATE_DTTM\n"
        "\t\t\ttoColumn: DimCustomer.CustomerKey\n"
    )
    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "Dashboard Filter Test"}).json()["id"]
    resp = client.post(
        f"/api/projects/{project_id}/ingest",
        files={"file": ("x.tmdl", raw.encode(), "application/octet-stream")},
    )
    assert resp.status_code == 200
    assert resp.json()["tables_extracted"] == 3  # raw extraction still reports everything parsed

    dashboard = client.get(f"/api/projects/{project_id}/dashboard").json()
    assert dashboard["tables"] == 2  # RUN_DATES, DimCustomer — not the auto-date table
    assert dashboard["relationships"] == 1  # r2 only — r1 touches the auto-date table

    # The raw inventory endpoints still return everything — hiding system
    # tables by default is a presentation choice made in the frontend, not
    # data loss in the API.
    tables = client.get(f"/api/projects/{project_id}/powerbi/tables").json()
    assert len(tables) == 3


def test_ingest_tmdl_file_end_to_end(db_session, sample_data_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    project_id = client.post("/api/projects", json={"name": "TMDL Project"}).json()["id"]
    path = os.path.join(sample_data_dir, "finance_model.tmdl")
    with open(path, "rb") as f:
        resp = client.post(
            f"/api/projects/{project_id}/ingest",
            files={"file": ("finance_model.tmdl", f, "application/octet-stream")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["detected_schema"] == "tmdl"
    assert body["tables_extracted"] == 2
    assert body["measures_extracted"] == 4

    tables = client.get(f"/api/projects/{project_id}/powerbi/tables").json()
    assert {t["name"] for t in tables} == {"FactSales", "DimCustomer"}

    project = client.get(f"/api/projects/{project_id}").json()
    assert project["source_artifacts"][0]["file_type"] == "tmdl"
