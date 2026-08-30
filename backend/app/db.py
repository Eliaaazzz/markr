"""Database access for the Markr service."""

import logging
import os
import time
from collections.abc import Sequence

import sqlalchemy as sa

from .ingest import StudentResult

logger = logging.getLogger("markr.db")

NOTIFY_CHANNEL = "markr_results"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS student_results (
    test_id         TEXT        NOT NULL CHECK (char_length(test_id) <= 64),
    student_number  TEXT        NOT NULL CHECK (char_length(student_number) <= 64),
    first_name      TEXT,
    last_name       TEXT,
    marks_available INTEGER     NOT NULL CHECK (marks_available BETWEEN 1 AND 10000),
    marks_obtained  INTEGER     NOT NULL CHECK (marks_obtained BETWEEN 0 AND 10000),
    last_scanned_at TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (test_id, student_number)
)
"""

# One row per test, maintained inside the import transaction. version only
# moves when an import actually changed a row, which is what lets the
# dashboard ETag and the change notifications stay quiet through idempotent
# re-imports.
_SUMMARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS test_summaries (
    test_id         TEXT        PRIMARY KEY,
    student_count   INTEGER     NOT NULL,
    marks_available INTEGER     NOT NULL,
    version         BIGINT      NOT NULL DEFAULT 1,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

# Startup reconciliation: recompute every summary from the result rows,
# creating missing rows and correcting any an older version left wrong. The
# guard means a routine restart changes nothing and bumps no versions, so
# fleet ETags survive deploys; only a summary that actually disagrees with
# its rows gets rewritten, and its version moves because what dashboards
# display changes with it.
_SUMMARY_RECONCILE = """
INSERT INTO test_summaries (test_id, student_count, marks_available)
SELECT test_id, COUNT(*), MAX(marks_available)
FROM student_results
GROUP BY test_id
ON CONFLICT (test_id) DO UPDATE SET
    student_count   = EXCLUDED.student_count,
    marks_available = EXCLUDED.marks_available,
    version         = test_summaries.version + 1,
    updated_at      = now()
WHERE test_summaries.student_count   IS DISTINCT FROM EXCLUDED.student_count
   OR test_summaries.marks_available IS DISTINCT FROM EXCLUDED.marks_available
"""

_engine: sa.Engine | None = None


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://markr:markr@localhost:5432/markr"
    )


def engine() -> sa.Engine:
    if _engine is None:
        raise RuntimeError("database not initialised; call init() first")
    return _engine


def init(attempts: int = 30, delay: float = 1.0) -> None:
    """Connect and apply the schema, waiting out a database that is still booting.

    Instances can turn off at any time, so a fresh backend must cope with a
    Postgres that is a few seconds behind it.
    """
    global _engine
    # hide_parameters keeps student marks and identifiers out of driver
    # error messages, which land in logs verbatim.
    _engine = sa.create_engine(
        database_url(), pool_pre_ping=True, hide_parameters=True
    )
    for attempt in range(1, attempts + 1):
        try:
            with _engine.begin() as conn:
                conn.execute(sa.text(_SCHEMA))
                conn.execute(sa.text(_SUMMARY_SCHEMA))
                conn.execute(sa.text(_SUMMARY_RECONCILE))
            return
        except sa.exc.OperationalError:
            if attempt == attempts:
                raise
            logger.warning("database not ready, retrying (%d/%d)", attempt, attempts)
            time.sleep(delay)


# One statement for the whole document. unnest zips the arrays into rows,
# GREATEST implements the keep-the-maximum re-scan rule atomically, the WHERE
# clause skips rows nothing would change, and RETURNING names the tests whose
# rows actually moved, which drives the summary refresh below.
_UPSERT = sa.text("""
    INSERT INTO student_results (
        test_id, student_number, first_name, last_name,
        marks_available, marks_obtained, last_scanned_at
    )
    SELECT * FROM unnest(
        CAST(:test_ids AS text[]),
        CAST(:student_numbers AS text[]),
        CAST(:first_names AS text[]),
        CAST(:last_names AS text[]),
        CAST(:availables AS int[]),
        CAST(:obtaineds AS int[]),
        CAST(:scanned_ats AS timestamptz[])
    )
    ON CONFLICT (test_id, student_number) DO UPDATE SET
        marks_obtained  = GREATEST(student_results.marks_obtained,  EXCLUDED.marks_obtained),
        marks_available = GREATEST(student_results.marks_available, EXCLUDED.marks_available),
        last_scanned_at = GREATEST(student_results.last_scanned_at, EXCLUDED.last_scanned_at),
        updated_at      = now()
    WHERE EXCLUDED.marks_obtained  > student_results.marks_obtained
       OR EXCLUDED.marks_available > student_results.marks_available
       OR EXCLUDED.last_scanned_at > student_results.last_scanned_at
       OR (student_results.last_scanned_at IS NULL
           AND EXCLUDED.last_scanned_at IS NOT NULL)
    RETURNING test_id
    """)

# The refresh is lock-then-recompute, in that order, because READ COMMITTED
# takes a statement's snapshot at statement start: a single upsert-with-
# aggregate could block on a concurrent import's row lock and then overwrite
# the summary with a count computed before that import committed. Locking
# first means the recompute statement's snapshot always includes every
# committed row.
_SUMMARY_ENSURE = sa.text("""
    INSERT INTO test_summaries (test_id, student_count, marks_available)
    SELECT t, 0, 0 FROM unnest(CAST(:test_ids AS text[])) AS t
    ON CONFLICT (test_id) DO NOTHING
    """)

_SUMMARY_LOCK = sa.text("""
    SELECT test_id FROM test_summaries
    WHERE test_id = ANY(CAST(:test_ids AS text[]))
    ORDER BY test_id
    FOR UPDATE
    """)

_SUMMARY_RECOMPUTE = sa.text("""
    UPDATE test_summaries ts SET
        student_count   = agg.student_count,
        marks_available = agg.marks_available,
        version         = ts.version + 1,
        updated_at      = now()
    FROM (
        SELECT test_id, COUNT(*) AS student_count,
               MAX(marks_available) AS marks_available
        FROM student_results
        WHERE test_id = ANY(CAST(:test_ids AS text[]))
        GROUP BY test_id
    ) AS agg
    WHERE ts.test_id = agg.test_id
    """)

# pg_notify inside the transaction is delivered on commit, so listeners can
# never observe a version that is not yet visible.
_NOTIFY = sa.text(
    "SELECT pg_notify(:channel, t) FROM unnest(CAST(:test_ids AS text[])) AS t"
)


def upsert_results(rows: Sequence[StudentResult]) -> int:
    """Persist one document's merged rows in a single transaction.

    Returns the number of rows actually written. Tests whose rows changed get
    their summary refreshed and version bumped in the same transaction, and a
    change notification queued for commit; an idempotent re-import writes
    nothing, bumps nothing, and notifies nobody.
    """
    if not rows:
        return 0
    # Sorted rows mean every concurrent import acquires its row locks in the
    # same global order, so two documents sharing students can wait on each
    # other and never deadlock.
    rows = sorted(rows, key=lambda r: (r.test_id, r.student_number))
    payload = {
        "test_ids": [r.test_id for r in rows],
        "student_numbers": [r.student_number for r in rows],
        "first_names": [r.first_name for r in rows],
        "last_names": [r.last_name for r in rows],
        "availables": [r.marks_available for r in rows],
        "obtaineds": [r.marks_obtained for r in rows],
        "scanned_ats": [r.scanned_at for r in rows],
    }
    with engine().begin() as conn:
        written = [row.test_id for row in conn.execute(_UPSERT, payload)]
        changed_tests = sorted(set(written))
        if changed_tests:
            ids = {"test_ids": changed_tests}
            conn.execute(_SUMMARY_ENSURE, ids)
            conn.execute(_SUMMARY_LOCK, ids)
            conn.execute(_SUMMARY_RECOMPUTE, ids)
            conn.execute(
                _NOTIFY, {"channel": NOTIFY_CHANNEL, "test_ids": changed_tests}
            )
        return len(written)


def fetch_results(test_id: str) -> list[tuple[int, int]]:
    """(obtained, available) pairs for one test; empty when the test is unknown."""
    with engine().connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT marks_obtained, marks_available FROM student_results "
                "WHERE test_id = :test_id"
            ),
            {"test_id": test_id},
        ).all()
    return [(row.marks_obtained, row.marks_available) for row in rows]


# All eight statistics and all ten bins in one statement, so the numbers a
# poll returns always describe one snapshot and only the scan crosses the
# wire. percentile_cont is linear interpolation, the same R-7 rule the
# reference implementation in stats.py uses; rounding happens in Python so
# both paths round identically.
_STATS = sa.text("""
    WITH pcts AS (
        SELECT marks_obtained::float8 / marks_available * 100 AS pct
        FROM student_results
        WHERE test_id = :test_id
    )
    SELECT
        count(*)                                            AS count,
        avg(pct)                                            AS mean,
        stddev_pop(pct)                                     AS stddev,
        min(pct)                                            AS min,
        max(pct)                                            AS max,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY pct)   AS p25,
        percentile_cont(0.5)  WITHIN GROUP (ORDER BY pct)   AS p50,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY pct)   AS p75,
        count(*) FILTER (WHERE least(floor(pct / 10), 9) = 0) AS b0,
        count(*) FILTER (WHERE least(floor(pct / 10), 9) = 1) AS b1,
        count(*) FILTER (WHERE least(floor(pct / 10), 9) = 2) AS b2,
        count(*) FILTER (WHERE least(floor(pct / 10), 9) = 3) AS b3,
        count(*) FILTER (WHERE least(floor(pct / 10), 9) = 4) AS b4,
        count(*) FILTER (WHERE least(floor(pct / 10), 9) = 5) AS b5,
        count(*) FILTER (WHERE least(floor(pct / 10), 9) = 6) AS b6,
        count(*) FILTER (WHERE least(floor(pct / 10), 9) = 7) AS b7,
        count(*) FILTER (WHERE least(floor(pct / 10), 9) = 8) AS b8,
        count(*) FILTER (WHERE least(floor(pct / 10), 9) = 9) AS b9
    FROM pcts
    """)


def fetch_dashboard(test_id: str) -> dict | None:
    """Aggregate and histogram from one statement; None for an unknown test."""
    with engine().connect() as conn:
        row = conn.execute(_STATS, {"test_id": test_id}).one()
    if row.count == 0:
        return None
    aggregate = {
        "mean": round(row.mean, 2),
        "stddev": round(row.stddev, 2),
        "min": round(row.min, 2),
        "max": round(row.max, 2),
        "p25": round(row.p25, 2),
        "p50": round(row.p50, 2),
        "p75": round(row.p75, 2),
        "count": row.count,
    }
    counts = [getattr(row, f"b{i}") for i in range(10)]
    histogram = {
        "bins": [
            {"lower_pct": i * 10, "upper_pct": (i + 1) * 10, "count": counts[i]}
            for i in range(10)
        ],
        "total": row.count,
    }
    return {"aggregate": aggregate, "histogram": histogram}


def fetch_freshness(test_id: str) -> tuple[int, float] | None:
    """(version, updated_at epoch) for a test, or None when it is unknown.

    A single-row indexed read, so an unchanged poll costs almost nothing:
    the dashboard endpoint folds both values into its ETag and answers 304
    without touching the results table. The timestamp matters as much as
    the counter: versions restart when a database is rebuilt, so a counter
    alone could collide with an ETag a browser cached against the previous
    database and serve it stale results forever.
    """
    with engine().connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT version, updated_at FROM test_summaries "
                "WHERE test_id = :test_id"
            ),
            {"test_id": test_id},
        ).one_or_none()
    if row is None:
        return None
    return row.version, row.updated_at.timestamp()


_LIST_TESTS = sa.text("""
    SELECT test_id, student_count, marks_available
    FROM test_summaries
    ORDER BY
        (test_id ~ '^[0-9]+$') DESC,
        CASE WHEN test_id ~ '^[0-9]+$' THEN test_id::numeric END,
        test_id
    """)


def list_tests() -> list[dict]:
    """Every known test from the summary table, so the listing never scans
    student rows. All-digit ids sort by numeric value ('0001' before '10');
    numeric copes with the full 64-digit ids the ingest cap allows.
    """
    with engine().connect() as conn:
        rows = conn.execute(_LIST_TESTS).all()
    return [
        {
            "test_id": row.test_id,
            "student_count": row.student_count,
            "marks_available": row.marks_available,
        }
        for row in rows
    ]


def ping() -> bool:
    try:
        with engine().connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        return True
    except sa.exc.SQLAlchemyError:
        return False


def dispose() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
