from app.graph.builder import build_nodes_and_edges
from app.ingestion.json.detector import detect
from app.ingestion.json.powerbi_json_adapter import extract_semantic_model
from app.ingestion.tmdl.tmdl_adapter import extract_semantic_model_from_tmdl
from app.parsers.dax.dependency_parser import resolve_dependencies


def _finance_model(sample_data_dir):
    import os

    with open(os.path.join(sample_data_dir, "finance_model.json")) as f:
        raw = f.read()
    detection = detect(raw)
    model = extract_semantic_model(
        detection.payload, source_file="finance_model.json", project_id="p1", model_name="Finance"
    )
    resolve_dependencies(model)
    return model


def test_graph_has_expected_node_types(sample_data_dir):
    model = _finance_model(sample_data_dir)
    nodes, edges = build_nodes_and_edges([model])

    node_types = {n.node_type for n in nodes}
    assert node_types == {"SOURCE", "SEMANTIC_MODEL", "TABLE", "COLUMN", "MEASURE"}

    source_nodes = [n for n in nodes if n.node_type == "SOURCE"]
    assert [n.label for n in source_nodes] == ["finance_model.json"]

    table_nodes = [n for n in nodes if n.node_type == "TABLE"]
    assert len(table_nodes) == 4

    measure_nodes = [n for n in nodes if n.node_type == "MEASURE"]
    assert len(measure_nodes) == 5


def test_graph_has_measure_to_measure_and_measure_to_column_edges(sample_data_dir):
    model = _finance_model(sample_data_dir)
    nodes, edges = build_nodes_and_edges([model])

    edge_types = {e.edge_type for e in edges}
    assert "MEASURE_TO_MEASURE" in edge_types
    assert "MEASURE_TO_COLUMN" in edge_types
    assert "TABLE_TO_TABLE" in edge_types

    node_by_id = {n.id: n for n in nodes}
    m2m = [e for e in edges if e.edge_type == "MEASURE_TO_MEASURE"]
    labels = {(node_by_id[e.source_node_id].label, node_by_id[e.target_node_id].label) for e in m2m}
    assert ("Gross Margin", "Total Revenue") in labels
    assert ("Gross Margin", "Total Cost") in labels


def test_measure_node_detail_carries_dax_and_dependencies(sample_data_dir):
    model = _finance_model(sample_data_dir)
    nodes, _edges = build_nodes_and_edges([model])

    gross_margin = next(n for n in nodes if n.node_type == "MEASURE" and n.label == "Gross Margin")
    assert gross_margin.detail["expression"] == "[Total Revenue] - [Total Cost]"
    assert set(gross_margin.detail["referenced_measures"]) == {"Total Revenue", "Total Cost"}
    assert gross_margin.detail["table"]

    revenue_column = next(n for n in nodes if n.node_type == "COLUMN" and n.label.endswith(".Revenue"))
    assert revenue_column.detail["data_type"]
    assert "expression" in revenue_column.detail


def test_auto_date_table_nodes_are_flagged_system_and_ordinary_nodes_are_not():
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
    nodes, _edges = build_nodes_and_edges([model])

    run_dates_node = next(n for n in nodes if n.node_type == "TABLE" and n.label == "RUN_DATES")
    assert run_dates_node.is_system is False

    date_table_node = next(n for n in nodes if n.node_type == "TABLE" and n.label.startswith("Date Table"))
    assert date_table_node.is_system is True

    date_column_node = next(n for n in nodes if n.node_type == "COLUMN" and n.label.endswith(".Date"))
    assert date_column_node.is_system is True
