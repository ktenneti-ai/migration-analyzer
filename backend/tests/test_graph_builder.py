from app.graph.builder import build_nodes_and_edges
from app.ingestion.json.detector import detect
from app.ingestion.json.powerbi_json_adapter import extract_semantic_model
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
    assert node_types == {"SEMANTIC_MODEL", "TABLE", "COLUMN", "MEASURE"}

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
