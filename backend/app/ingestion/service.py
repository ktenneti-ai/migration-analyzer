"""Orchestrates one file's ingestion: detect -> extract -> resolve deps ->
persist -> rebuild graph. This is the single entry point the API layer
calls; it is format-agnostic at the top (dispatches on DetectedSchema) so
adding PBIX/SQL adapters later means adding a branch here, not a new
pipeline (spec section 3).
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.graph import builder as graph_builder
from app.ingestion.json.detector import DetectedSchema, InvalidJSONError, detect
from app.ingestion.json.powerbi_json_adapter import extract_semantic_model
from app.ingestion.tmdl.tmdl_adapter import extract_semantic_model_from_tmdl
from app.metadata import store
from app.metadata.models import PowerBISemanticModel, SourceArtifact
from app.parsers.dax.classifier import classify_measures, detect_relationship_model_gaps
from app.parsers.dax.dependency_parser import resolve_dependencies

_FILE_TYPE_BY_SCHEMA = {DetectedSchema.TMDL: "tmdl"}


class IngestionError(ValueError):
    pass


def ingest_json_file(session: Session, project_id: str, filename: str, raw_text: str) -> dict:
    data = store.get_project_data(session, project_id)
    if data is None:
        raise IngestionError(f"Unknown project {project_id}")

    try:
        detection = detect(raw_text)
    except InvalidJSONError as exc:
        raise IngestionError(str(exc)) from exc

    artifact = SourceArtifact(
        id=store.new_id(),
        filename=filename,
        file_type=_FILE_TYPE_BY_SCHEMA.get(detection.schema, "json"),
        raw_schema_summary=detection.summary,
        detected_schema=detection.schema.value,
    )
    data.project.source_artifacts.append(artifact)

    model_name = filename.rsplit(".", 1)[0]
    semantic_model: PowerBISemanticModel | None = None
    if detection.schema == DetectedSchema.POWER_BI_MODEL:
        semantic_model = extract_semantic_model(
            detection.payload, source_file=filename, project_id=project_id, model_name=model_name
        )
    elif detection.schema == DetectedSchema.TMDL:
        semantic_model = extract_semantic_model_from_tmdl(
            detection.payload["raw_text"], source_file=filename, project_id=project_id, model_name=model_name
        )
    # TERADATA / DATABRICKS / UNKNOWN_GENERIC: file is recorded (provenance
    # preserved) but not yet extracted into canonical objects — later
    # milestones add those adapters. Nothing is fabricated in the meantime.

    new_gaps = []
    if semantic_model is not None:
        new_gaps = resolve_dependencies(semantic_model)
        classify_measures(semantic_model)
        new_gaps = new_gaps + detect_relationship_model_gaps(semantic_model)
        data.semantic_models.append(semantic_model)

    data.gaps.extend(new_gaps)
    store.save_project_data(session, data)

    nodes, edges = graph_builder.build_nodes_and_edges(data.semantic_models)
    graph_json = graph_builder.to_json_dict(nodes, edges)
    store.save_graph_snapshot(session, project_id, json.dumps(graph_json))

    return {
        "artifact": artifact.model_dump(),
        "detected_schema": detection.schema.value,
        "tables_extracted": sum(len(m.tables) for m in data.semantic_models),
        "measures_extracted": sum(len(t.measures) for m in data.semantic_models for t in m.tables),
        "gaps_found": len(new_gaps),
    }
