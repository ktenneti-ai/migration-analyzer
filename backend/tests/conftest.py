"""Sets the test SQLite DB path before any test module imports app.db.session
(module-level, so it runs during pytest collection, before app.* is
imported anywhere) and provides a clean DB session per test.
"""
import os
import tempfile

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["MIGRATION_ANALYZER_DB"] = _TEST_DB_PATH

import pytest  # noqa: E402


@pytest.fixture()
def db_session():
    from app.db.models_orm import ProjectRecord
    from app.db.session import get_session, init_db

    init_db()
    session = get_session()
    try:
        yield session
    finally:
        session.query(ProjectRecord).delete()
        session.commit()
        session.close()


@pytest.fixture()
def sample_data_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "..", "sample_data")
