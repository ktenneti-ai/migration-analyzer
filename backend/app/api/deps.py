from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.db.session import get_session


def db_session() -> Iterator[Session]:
    session = get_session()
    try:
        yield session
    finally:
        session.close()
