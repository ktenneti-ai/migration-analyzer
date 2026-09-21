"""Spec section 18/19 (Gold design: facts, dimensions, bridges, aggregates
— the "metric view"). Facts/dimensions are inferred from Power BI metadata
alone (backend/app/recommendations/gold_design.py), each candidate fact with
at least one translatable measure gets a provisional Metric View YAML spec
(backend/app/recommendations/metric_view_yaml.py), and measures that need
window functions/LAG/RANK get a companion wrapper view
(backend/app/recommendations/wrapper_views.py) — real evidence, no
Teradata/Databricks needed. Bridges, aggregates, and confirmed fact grain
still require the Databricks migration engine and Teradata source data,
neither of which exists yet, so those stay empty with an explicit reason
rather than being fabricated.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.metadata import store
from app.recommendations.gold_design import detect_fact_groups
from app.recommendations.metric_view_yaml import build_metric_view_specs, render_yaml
from app.recommendations.wrapper_views import build_wrapper_views

router = APIRouter(prefix="/api/projects", tags=["metric-view"])


def _all_metric_view_specs(data) -> list:
    specs = []
    for model in data.semantic_models:
        specs.extend(build_metric_view_specs(model))
    return specs


def _all_wrapper_specs(data) -> list:
    specs = []
    for model in data.semantic_models:
        specs.extend(build_wrapper_views(model))
    return specs


@router.get("/{project_id}/gold")
def gold_design(project_id: str, session: Session = Depends(db_session)):
    data = store.get_project_data(session, project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")

    facts, dimensions = [], []
    for model in data.semantic_models:
        model_facts, model_dimensions = detect_fact_groups(model)
        facts.extend(model_facts)
        dimensions.extend(model_dimensions)

    metric_views = _all_metric_view_specs(data)
    wrapper_views = _all_wrapper_specs(data)

    return {
        "pending": len(facts) == 0,
        "reason": (
            "No Power BI semantic model has been ingested yet, so there is nothing to infer "
            "candidate fact/dimension tables from."
            if not facts
            else "Facts and dimensions below are inferred from Power BI DAX and relationships "
            "(status INFERRED). Fact grain, bridge tables, and aggregates still require "
            "Teradata source data and the Databricks migration engine, neither of which is "
            "ingested yet."
        ),
        "facts": [f.model_dump() for f in facts],
        "dimensions": [d.model_dump() for d in dimensions],
        "bridges": [],
        "aggregates": [],
        "metric_views": [{**spec.model_dump(), "yaml": render_yaml(spec)} for spec in metric_views],
        "wrapper_views": [spec.model_dump() for spec in wrapper_views],
    }


@router.get("/{project_id}/gold/metric-view/{fact_table}/export")
def export_metric_view(project_id: str, fact_table: str, session: Session = Depends(db_session)):
    data = store.get_project_data(session, project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")

    spec = next((s for s in _all_metric_view_specs(data) if s.fact_table == fact_table), None)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No metric view spec for fact table '{fact_table}'")

    filename = f"metric_view_{fact_table}.yaml"
    return Response(
        content=render_yaml(spec),
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{project_id}/gold/wrapper-view/{fact_table}/export")
def export_wrapper_view(project_id: str, fact_table: str, session: Session = Depends(db_session)):
    data = store.get_project_data(session, project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")

    spec = next((s for s in _all_wrapper_specs(data) if s.fact_table == fact_table), None)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No wrapper view spec for fact table '{fact_table}'")

    filename = f"wrapper_view_{fact_table}.sql"
    return Response(
        content=spec.sql,
        media_type="application/sql",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
