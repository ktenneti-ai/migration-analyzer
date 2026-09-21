from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models_orm import ProjectRecord
from app.metadata.models import Project, ProjectData


def new_id() -> str:
    return uuid.uuid4().hex


def create_project(session: Session, name: str) -> ProjectData:
    project = Project(id=new_id(), name=name)
    data = ProjectData(project=project)
    record = ProjectRecord(
        id=project.id,
        name=project.name,
        created_at=project.created_at,
        canonical_json=data.model_dump_json(),
        graph_json="{}",
    )
    session.add(record)
    session.commit()
    return data


def list_projects(session: Session) -> list[Project]:
    records = session.query(ProjectRecord).order_by(ProjectRecord.created_at.desc()).all()
    return [ProjectData.model_validate_json(r.canonical_json).project for r in records]


def delete_project(session: Session, project_id: str) -> bool:
    """Returns True if a project was deleted, False if it didn't exist."""
    record = session.get(ProjectRecord, project_id)
    if record is None:
        return False
    session.delete(record)
    session.commit()
    return True


def delete_all_projects(session: Session) -> int:
    """Returns the number of projects deleted."""
    count = session.query(ProjectRecord).delete()
    session.commit()
    return count


def get_project_data(session: Session, project_id: str) -> ProjectData | None:
    record = session.get(ProjectRecord, project_id)
    if record is None:
        return None
    return ProjectData.model_validate_json(record.canonical_json)


def save_project_data(session: Session, data: ProjectData) -> None:
    record = session.get(ProjectRecord, data.project.id)
    if record is None:
        raise ValueError(f"Unknown project {data.project.id}")
    record.canonical_json = data.model_dump_json()
    session.add(record)
    session.commit()


def save_graph_snapshot(session: Session, project_id: str, graph_json: str) -> None:
    record = session.get(ProjectRecord, project_id)
    if record is None:
        raise ValueError(f"Unknown project {project_id}")
    record.graph_json = graph_json
    session.add(record)
    session.commit()


def get_graph_snapshot(session: Session, project_id: str) -> str | None:
    record = session.get(ProjectRecord, project_id)
    if record is None:
        return None
    return record.graph_json
