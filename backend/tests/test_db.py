"""Unit tests for the database module's lifecycle and failure paths.

These need no Postgres. The engine is replaced with a stub so the retry loop,
the uninitialised guard, and the health probe can be driven directly; the
paths they cover only run when the database is missing or falling over, which
is exactly when they must behave.
"""

import pytest
import sqlalchemy as sa

from app import db


class _Ctx:
    """Stands in for a connection used as a context manager."""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.executed = []

    def execute(self, statement, *args):
        if self.error is not None:
            raise self.error
        self.executed.append(statement)
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _operational_error() -> sa.exc.OperationalError:
    return sa.exc.OperationalError("SELECT 1", {}, Exception("connection refused"))


class _StubEngine:
    """Fails `fail_times` times before succeeding, counting every attempt."""

    def __init__(self, fail_times: int = 0, error: Exception | None = None):
        self.fail_times = fail_times
        self.error = error
        self.attempts = 0
        self.disposed = False

    def _next(self):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise self.error or _operational_error()
        return _Ctx()

    def begin(self):
        return self._next()

    def connect(self):
        return self._next()

    def dispose(self):
        self.disposed = True


@pytest.fixture()
def stub(monkeypatch):
    """Isolate the module global so the real engine survives these tests."""
    monkeypatch.setattr(db, "_engine", None)

    def install(engine):
        monkeypatch.setattr(db.sa, "create_engine", lambda *a, **k: engine)
        monkeypatch.setattr(db.time, "sleep", lambda _: None)
        return engine

    return install


def test_engine_refuses_to_hand_out_an_uninitialised_connection(monkeypatch):
    monkeypatch.setattr(db, "_engine", None)
    with pytest.raises(RuntimeError, match="not initialised"):
        db.engine()


def test_init_waits_out_a_database_that_is_still_booting(stub):
    # Compose starts the backend beside Postgres, so the first few connects
    # losing is the normal case, not a failure.
    engine = stub(_StubEngine(fail_times=3))
    db.init(attempts=10, delay=0)
    assert engine.attempts == 4
    assert db.engine() is engine


def test_init_gives_up_after_the_last_attempt(stub):
    engine = stub(_StubEngine(fail_times=99))
    with pytest.raises(sa.exc.OperationalError):
        db.init(attempts=3, delay=0)
    assert engine.attempts == 3


def test_init_applies_the_schema(stub):
    stub(_StubEngine())
    db.init(attempts=1, delay=0)
    # A fresh volume gets its table; an existing one is left alone.
    assert "CREATE TABLE IF NOT EXISTS" in db._SCHEMA


def test_ping_reports_a_reachable_database(stub, monkeypatch):
    monkeypatch.setattr(db, "_engine", _StubEngine())
    assert db.ping() is True


def test_ping_reports_a_database_that_is_down(monkeypatch):
    # /health answers 503 off this, so a false positive would keep a broken
    # container in the load balancer.
    monkeypatch.setattr(db, "_engine", _StubEngine(fail_times=99))
    assert db.ping() is False


def test_ping_does_not_swallow_programming_faults(monkeypatch):
    # SQLAlchemyError only. A bug in our own code must surface, not read as
    # "the database is down".
    monkeypatch.setattr(db, "_engine", _StubEngine(fail_times=99, error=TypeError("bug")))
    with pytest.raises(TypeError):
        db.ping()


def test_dispose_releases_the_pool_and_clears_the_global(monkeypatch):
    engine = _StubEngine()
    monkeypatch.setattr(db, "_engine", engine)
    db.dispose()
    assert engine.disposed is True
    assert db._engine is None


def test_dispose_is_safe_to_call_twice(monkeypatch):
    monkeypatch.setattr(db, "_engine", None)
    db.dispose()
    db.dispose()
    assert db._engine is None


def test_upsert_of_an_empty_document_touches_no_connection(monkeypatch):
    # A document that parses to nothing must not open a transaction.
    engine = _StubEngine(fail_times=99)
    monkeypatch.setattr(db, "_engine", engine)
    db.upsert_results([])
    assert engine.attempts == 0
