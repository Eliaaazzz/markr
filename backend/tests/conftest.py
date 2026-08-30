"""Shared fixtures.

API tests need a reachable Postgres server. They never touch the application
database: the configured DATABASE_URL has its database name suffixed with
`_test` (created on demand), and the truncation guard refuses anything else,
so following the README's test instructions can never destroy real results.
Without a reachable server those tests skip and the pure unit tests still run.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from app import db

FIXTURES = Path(__file__).parent / "fixtures"


def _test_database_url() -> str:
    url = make_url(db.database_url())
    name = url.database or "markr"
    if not name.endswith("_test"):
        url = url.set(database=f"{name}_test")
    return url.render_as_string(hide_password=False)


TEST_DATABASE_URL = _test_database_url()


def _ensure_test_database() -> bool:
    """Create the test database if the server is up; report reachability."""
    url = make_url(TEST_DATABASE_URL)
    admin = url.set(database="postgres")
    try:
        engine = sa.create_engine(
            admin.render_as_string(hide_password=False),
            connect_args={"connect_timeout": 2},
            isolation_level="AUTOCOMMIT",
        )
        with engine.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            ).scalar()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE "{url.database}"'))
        engine.dispose()
        return True
    except sa.exc.SQLAlchemyError:
        return False


requires_db = pytest.mark.skipif(
    not _ensure_test_database(),
    reason="Postgres unreachable; run via the backend Dockerfile test stage",
)


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    with TestClient(app) as test_client:  # context manager runs the lifespan
        database = db.engine().url.database or ""
        if not database.endswith("_test"):
            raise RuntimeError(f"refusing to truncate non-test database {database!r}")
        with db.engine().begin() as conn:
            conn.execute(sa.text("TRUNCATE student_results, test_summaries"))
        yield test_client


@pytest.fixture()
def raising_client(monkeypatch):
    """A client that returns the 500 response instead of re-raising.

    TestClient re-raises server exceptions by default, which hides the
    application's own Exception handler. Turning that off is the only way to
    assert on what a caller would actually receive from a machine fault.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
