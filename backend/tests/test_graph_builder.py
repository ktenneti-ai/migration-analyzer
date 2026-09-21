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


def test_two_models_with_the_same_table_and_measure_names_stay_separate():
    # Two separate Power BI files ingested into one project can easily share
    # table/column/measure names (e.g. both have a "Sales" table with a
    # "Revenue" column) without being the same object. The lineage graph
    # must not silently merge them just because the names collide.
    raw = (
        "createOrReplace\n"
        "\tmodel Model\n"
        "\t\ttable Sales\n"
        "\t\t\tcolumn Revenue\n"
        "\t\t\t\tdataType: decimal\n"
        "\t\t\tmeasure Total = SUM(Sales[Revenue])\n"
    )
    model_a = extract_semantic_model_from_tmdl(raw, source_file="a.tmdl", project_id="p1", model_name="A")
    resolve_dependencies(model_a)
    model_b = extract_semantic_model_from_tmdl(raw, source_file="b.tmdl", project_id="p1", model_name="B")
    resolve_dependencies(model_b)

    nodes, edges = build_nodes_and_edges([model_a, model_b])

    table_nodes = [n for n in nodes if n.node_type == "TABLE" and n.label == "Sales"]
    column_nodes = [n for n in nodes if n.node_type == "COLUMN" and n.label == "Sales.Revenue"]
    measure_nodes = [n for n in nodes if n.node_type == "MEASURE" and n.label == "Total"]
    assert len(table_nodes) == 2
    assert len(column_nodes) == 2
    assert len(measure_nodes) == 2

    # Each model's own "Total" measure must link to that same model's own
    # "Sales.Revenue" column — not its counterpart in the other model.
    m2c = {e.source_node_id: e.target_node_id for e in edges if e.edge_type == "MEASURE_TO_COLUMN"}
    for measure_node in measure_nodes:
        linked_column_id = m2c[measure_node.id]
        column_node = next(c for c in column_nodes if c.id == linked_column_id)
        # The linked column must belong to the same table instance as the
        # measure (found via the measure's own MEASURE_TO_TABLE edge).
        measure_table_id = next(e.target_node_id for e in edges if e.source_node_id == measure_node.id and e.edge_type == "MEASURE_TO_TABLE")
        column_table_id = next(e.target_node_id for e in edges if e.source_node_id == column_node.id and e.edge_type == "COLUMN_TO_TABLE")
        assert measure_table_id == column_table_id


def test_teradata_backed_table_gets_a_teradata_source_node_and_edge():
    # The Teradata Assessment page links a Power BI table to its upstream
    # Teradata object via source_hint — the lineage graph must show the same
    # link, not just the assessment page, or the two would silently disagree.
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
        "\n"
        "\t\ttable DimCustomer\n"
        "\t\t\tcolumn CustomerKey\n"
        "\t\t\t\tdataType: int64\n"
    )
    model = extract_semantic_model_from_tmdl(raw, source_file="x.tmdl", project_id="p1", model_name="X")
    nodes, edges = build_nodes_and_edges([model])

    teradata_nodes = [n for n in nodes if n.node_type == "TERADATA_SOURCE"]
    assert len(teradata_nodes) == 1
    assert teradata_nodes[0].label == "BNRPROD.CP_ED.V_CPED_RUN_DATES"
    assert teradata_nodes[0].detail == {
        "database": "BNRPROD",
        "schema": "CP_ED",
        "object": "V_CPED_RUN_DATES",
        "object_type": "VIEW",
    }

    run_dates_node = next(n for n in nodes if n.node_type == "TABLE" and n.label == "RUN_DATES")
    td_edges = [e for e in edges if e.edge_type == "TERADATA_TO_TABLE"]
    assert len(td_edges) == 1
    assert td_edges[0].source_node_id == teradata_nodes[0].id
    assert td_edges[0].target_node_id == run_dates_node.id

    # DimCustomer has no Teradata-recognized partition -> no Teradata node
    # or edge attached to it.
    dim_customer_node = next(n for n in nodes if n.node_type == "TABLE" and n.label == "DimCustomer")
    assert not any(e.target_node_id == dim_customer_node.id and e.edge_type == "TERADATA_TO_TABLE" for e in edges)
