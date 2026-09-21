"""Builds the lineage graph from the canonical model.

LineageNode/LineageEdge are defined once in app.metadata.models (the
canonical model) and reused here rather than duplicated — this module's
job is only to derive a networkx graph (for traversal: impact analysis,
upstream/downstream) and a JSON-serializable snapshot (for the API/UI and
on-disk persistence) from that canonical data.
"""
from __future__ import annotations

import networkx as nx

from app.metadata.models import LineageEdge, LineageNode, PowerBISemanticModel
from app.metadata.store import new_id


def build_graph(models: list[PowerBISemanticModel]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    nodes, edges = build_nodes_and_edges(models)
    for node in nodes:
        graph.add_node(node.id, **node.model_dump())
    for edge in edges:
        graph.add_edge(edge.source_node_id, edge.target_node_id, **edge.model_dump())
    return graph


def build_nodes_and_edges(
    models: list[PowerBISemanticModel],
) -> tuple[list[LineageNode], list[LineageEdge]]:
    nodes: list[LineageNode] = []
    edges: list[LineageEdge] = []

    source_node_id: dict[str, str] = {}  # keyed by provenance.source_file
    model_node_id: dict[str, str] = {}
    table_node_id: dict[str, str] = {}  # keyed by (model_id, table_name)
    column_node_id: dict[str, str] = {}  # keyed by "table_name.column_name"
    measure_node_id: dict[str, str] = {}  # keyed by measure name (global, matches dependency_parser)

    for model in models:
        source_file = model.provenance.source_file
        s_id = source_node_id.get(source_file)
        if s_id is None:
            s_id = new_id()
            source_node_id[source_file] = s_id
            nodes.append(LineageNode(id=s_id, node_type="SOURCE", ref_id=source_file, label=source_file))

        m_id = new_id()
        model_node_id[model.id] = m_id
        nodes.append(
            LineageNode(
                id=m_id,
                node_type="SEMANTIC_MODEL",
                ref_id=model.id,
                label=model.name,
                detail={"tables": len(model.tables), "relationships": len(model.relationships)},
            )
        )
        edges.append(LineageEdge(id=new_id(), source_node_id=s_id, target_node_id=m_id, edge_type="SOURCE_TO_MODEL"))

        for table in model.tables:
            t_id = new_id()
            table_label = table.display_name or table.name
            is_system = table.display_name is not None
            table_node_id[f"{model.id}:{table.name}"] = t_id
            nodes.append(
                LineageNode(
                    id=t_id,
                    node_type="TABLE",
                    ref_id=table.id,
                    label=table_label,
                    is_system=is_system,
                    detail={
                        "real_name": table.name,
                        "columns": len(table.columns),
                        "measures": len(table.measures),
                        "source": table.source_hint,
                        "status": table.status,
                    },
                )
            )
            edges.append(
                LineageEdge(id=new_id(), source_node_id=t_id, target_node_id=m_id, edge_type="TABLE_TO_MODEL")
            )

            for column in table.columns:
                c_id = new_id()
                column_node_id[f"{table.name}.{column.name}"] = c_id
                nodes.append(
                    LineageNode(
                        id=c_id,
                        node_type="COLUMN",
                        ref_id=column.id,
                        label=f"{table_label}.{column.name}",
                        is_system=is_system,
                        detail={
                            "table": table_label,
                            "data_type": column.data_type,
                            "is_calculated": column.is_calculated,
                            "expression": column.expression,
                            "hidden": column.hidden,
                            "status": column.status,
                        },
                    )
                )
                edges.append(
                    LineageEdge(id=new_id(), source_node_id=c_id, target_node_id=t_id, edge_type="COLUMN_TO_TABLE")
                )

            for measure in table.measures:
                mm_id = new_id()
                measure_node_id[measure.name] = mm_id
                nodes.append(
                    LineageNode(
                        id=mm_id,
                        node_type="MEASURE",
                        ref_id=measure.id,
                        label=measure.name,
                        is_system=is_system,
                        detail={
                            "table": table_label,
                            "expression": measure.expression,
                            "referenced_measures": measure.referenced_measures,
                            "referenced_columns": measure.referenced_columns,
                            "dependent_tables": measure.dependent_tables,
                            "dependency_depth": measure.dependency_depth,
                            "complexity_band": measure.complexity_band,
                            "complexity_category": measure.complexity_category,
                            "status": measure.status,
                        },
                    )
                )
                edges.append(
                    LineageEdge(id=new_id(), source_node_id=mm_id, target_node_id=t_id, edge_type="MEASURE_TO_TABLE")
                )

        for rel in model.relationships:
            from_id = table_node_id.get(f"{model.id}:{rel.from_table}")
            to_id = table_node_id.get(f"{model.id}:{rel.to_table}")
            if from_id and to_id:
                edges.append(
                    LineageEdge(id=new_id(), source_node_id=from_id, target_node_id=to_id, edge_type="TABLE_TO_TABLE")
                )

    # Second pass: measure -> measure / measure -> column edges (needs all
    # measure nodes to exist first, since references can cross tables).
    for model in models:
        for table in model.tables:
            for measure in table.measures:
                src = measure_node_id.get(measure.name)
                if src is None:
                    continue
                for ref_measure in measure.referenced_measures:
                    dst = measure_node_id.get(ref_measure)
                    if dst:
                        edges.append(
                            LineageEdge(id=new_id(), source_node_id=src, target_node_id=dst, edge_type="MEASURE_TO_MEASURE")
                        )
                for ref_column in measure.referenced_columns:
                    dst = column_node_id.get(ref_column)
                    if dst:
                        edges.append(
                            LineageEdge(id=new_id(), source_node_id=src, target_node_id=dst, edge_type="MEASURE_TO_COLUMN")
                        )

    return nodes, edges


def to_json_dict(nodes: list[LineageNode], edges: list[LineageEdge]) -> dict:
    return {
        "nodes": [n.model_dump() for n in nodes],
        "edges": [e.model_dump() for e in edges],
    }
