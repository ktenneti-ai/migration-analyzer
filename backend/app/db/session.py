"""SQLite persistence.

Milestone 1 stores each project's canonical metadata and lineage graph as
JSON blobs alongside a relational project registry row. This avoids mapping
every nested canonical object into its own table before the model has
stabilized across later milestones (Teradata/Databricks extraction will add
fields); the canonical Pydantic models remain the single source of truth for
shape, SQLite is just the persistence substrate.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DB_PATH = os.environ.get("MIGRATION_ANALYZER_DB", "migration_analyzer.db")
ENGINE = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from app.db import models_orm  # noqa: F401  (registers tables on Base)

    Base.metadata.create_all(bind=ENGINE)


def get_session() -> Session:
    return SessionLocal()
