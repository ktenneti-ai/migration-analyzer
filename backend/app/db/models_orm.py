from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ProjectRecord(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    # JSON-serialized canonical model + lineage graph snapshot for this project.
    canonical_json: Mapped[str] = mapped_column(Text, default="{}")
    graph_json: Mapped[str] = mapped_column(Text, default="{}")
