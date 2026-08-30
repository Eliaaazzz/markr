"""API tests against a real Postgres; see conftest for the skip rule."""

import sqlalchemy as sa

from app import db

from .conftest import FIXTURES, requires_db

pytestmark = requires_db

MARKR = {"Content-Type": "text/xml+markr"}


def post_xml(client, body: bytes, content_type: str = "text/xml+markr"):
    return client.post("/import", content=body, headers={"Content-Type": content_type})


def stored_rows():
    with db.engine().connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT test_id, student_number, marks_available, marks_obtained "
                "FROM student_results ORDER BY test_id, student_number"
            )
        ).all()
    return [tuple(row) for row in rows]


def single_result(test_id: str, student: str, available: int, obtained: int) -> bytes:
    return f"""<mcq-test-results>
        <mcq-test-result scanned-on="2017-12-04T12:12:10+11:00">
            <student-number>{student}</student-number>
            <test-id>{test_id}</test-id>
            <summary-marks available="{available}" obtained="{obtained}" />
        </mcq-test-result>
    </mcq-test-results>""".encode()


def test_root_identifies_the_api_and_lists_its_public_endpoints(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "Markr API",
        "status": "running",
        "endpoints": {
            "import": "POST /import",
            "tests": "GET /tests",
            "aggregate": "GET /results/{test_id}/aggregate",
            "histogram": "GET /results/{test_id}/histogram",
            "dashboard": "GET /results/{test_id}/dashboard",
            "events": "GET /events",
            "health": "GET /health",
        },
    }


def test_import_brief_example(client):
    response = post_xml(client, (FIXTURES / "valid_single.xml").read_bytes())
    assert response.status_code == 200
    assert response.json() == {"imported": 1}
    assert stored_rows() == [("1234", "521585128", 20, 13)]


def test_import_requires_the_markr_content_type(client):
    body = (FIXTURES / "valid_single.xml").read_bytes()
    response = post_xml(client, body, content_type="application/xml")
    assert response.status_code == 400
    assert "error" in response.json()
    assert stored_rows() == []


def test_charset_parameter_is_tolerated(client):
    body = (FIXTURES / "valid_single.xml").read_bytes()
    response = post_xml(client, body, content_type="text/xml+markr; charset=utf-8")
    assert response.status_code == 200


def test_missing_content_type_rejected(client):
    response = client.post("/import", content=b"<mcq-test-results/>")
    assert response.status_code == 400


def test_oversized_body_rejected(client):
    body = b"<mcq-test-results>" + b" " * (10 * 1024 * 1024) + b"</mcq-test-results>"
    response = post_xml(client, body)
    assert response.status_code == 400
    assert "large" in response.json()["error"]


def test_malformed_xml_returns_the_brief_error_shape(client):
    response = post_xml(
        client, (FIXTURES / "malformed_unclosed_quote.xml").read_bytes()
    )
    assert response.status_code == 400
    assert response.json() == {"error": "Invalid XML format"}


def test_invalid_document_persists_nothing(client):
    post_xml(client, single_result("1234", "42", 20, 9))
    before = stored_rows()
    # first record valid, second missing its student number: reject everything
    response = post_xml(client, (FIXTURES / "missing_student_number.xml").read_bytes())
    assert response.status_code == 400
    assert "record 2" in response.json()["error"]
    assert stored_rows() == before


def test_empty_document_imports_zero(client):
    response = post_xml(client, (FIXTURES / "empty_root.xml").read_bytes())
    assert response.status_code == 200
    assert response.json() == {"imported": 0}


def test_sample_import_is_idempotent(client):
    body = (FIXTURES / "sample_results.xml").read_bytes()
    first = post_xml(client, body)
    assert first.status_code == 200
    assert first.json() == {"imported": 100}
    assert len(stored_rows()) == 81
    second = post_xml(client, body)
    assert second.json() == {"imported": 100}
    assert len(stored_rows()) == 81


def test_cross_request_merge_keeps_maxima_in_both_orders(client):
    post_xml(client, single_result("1234", "77", 20, 8))
    post_xml(client, single_result("1234", "77", 20, 13))
    assert stored_rows() == [("1234", "77", 20, 13)]

    post_xml(client, single_result("1234", "78", 20, 13))
    post_xml(client, single_result("1234", "78", 20, 8))
    assert ("1234", "78", 20, 13) in stored_rows()


def test_available_marks_merge_across_requests(client):
    post_xml(client, single_result("1234", "79", 10, 8))
    post_xml(client, single_result("1234", "79", 20, 6))
    assert stored_rows() == [("1234", "79", 20, 8)]


def test_aggregate_for_unknown_test_is_404(client):
    response = client.get("/results/nope/aggregate")
    assert response.status_code == 404
    assert response.json() == {"error": "Not found"}


def test_absurd_ids_on_read_paths_are_a_clean_404(client):
    long_id = "9" * 3000
    response = client.get(f"/results/{long_id}/aggregate")
    assert response.status_code == 404
    assert response.json() == {"error": "Not found"}

    response = client.get("/results/%00probe/histogram")
    assert response.status_code == 404
    assert response.json() == {"error": "Not found"}

    response = client.get("/results/%00probe/dashboard")
    assert response.status_code == 404
    assert response.json() == {"error": "Not found"}


def test_histogram_for_unknown_test_is_404(client):
    response = client.get("/results/nope/histogram")
    assert response.status_code == 404
    assert response.json() == {"error": "Not found"}


def test_aggregate_single_record_matches_the_brief(client):
    post_xml(client, (FIXTURES / "valid_single.xml").read_bytes())
    response = client.get("/results/1234/aggregate")
    assert response.status_code == 200
    assert response.json() == {
        "mean": 65.0,
        "stddev": 0.0,
        "min": 65.0,
        "max": 65.0,
        "p25": 65.0,
        "p50": 65.0,
        "p75": 65.0,
        "count": 1,
    }


def test_aggregate_for_the_sample_file(client):
    # Expected values computed independently from sample_results.xml after
    # applying the keep-the-maximum rule to its 19 re-scanned students.
    post_xml(client, (FIXTURES / "sample_results.xml").read_bytes())
    response = client.get("/results/9863/aggregate")
    assert response.json() == {
        "mean": 50.8,
        "stddev": 9.92,
        "min": 30.0,
        "max": 75.0,
        "p25": 45.0,
        "p50": 50.0,
        "p75": 55.0,
        "count": 81,
    }


def test_histogram_for_the_sample_file(client):
    post_xml(client, (FIXTURES / "sample_results.xml").read_bytes())
    response = client.get("/results/9863/histogram")
    body = response.json()
    assert [b["count"] for b in body["bins"]] == [0, 0, 0, 6, 28, 28, 14, 5, 0, 0]
    assert body["bins"][3] == {"lower_pct": 30, "upper_pct": 40, "count": 6}
    assert body["total"] == 81


def test_reimport_writes_no_rows(client):
    body = (FIXTURES / "sample_results.xml").read_bytes()
    post_xml(client, body)
    with db.engine().connect() as conn:
        before = conn.execute(
            sa.text("SELECT student_number, updated_at FROM student_results")
        ).all()
    post_xml(client, body)
    with db.engine().connect() as conn:
        after = conn.execute(
            sa.text("SELECT student_number, updated_at FROM student_results")
        ).all()
    assert sorted(before) == sorted(after)  # untouched rows keep their stamps


def test_reimport_leaves_every_read_endpoint_identical(client):
    body = (FIXTURES / "sample_results.xml").read_bytes()
    post_xml(client, body)
    before = (
        client.get("/results/9863/aggregate").json(),
        client.get("/results/9863/histogram").json(),
        client.get("/tests").json(),
    )
    post_xml(client, body)
    after = (
        client.get("/results/9863/aggregate").json(),
        client.get("/results/9863/histogram").json(),
        client.get("/tests").json(),
    )
    assert before == after


def test_tests_listing_is_empty_without_data(client):
    response = client.get("/tests")
    assert response.status_code == 200
    assert response.json() == {"tests": []}


def test_tests_listing_orders_numeric_ids_by_value(client):
    post_xml(client, single_result("999", "1", 10, 5))
    post_xml(client, single_result("56", "1", 10, 5))
    post_xml(client, single_result("1234", "1", 20, 5))
    post_xml(client, single_result("999", "2", 20, 5))
    body = client.get("/tests").json()
    assert [t["test_id"] for t in body["tests"]] == ["56", "999", "1234"]
    nine_nine_nine = body["tests"][1]
    assert nine_nine_nine["student_count"] == 2
    assert nine_nine_nine["marks_available"] == 20  # max across the test's scans
    assert all(isinstance(t["test_id"], str) for t in body["tests"])


def test_health_reports_ok_while_the_database_answers(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_503_when_the_database_is_down(client, monkeypatch):
    # The container healthcheck and the dashboard's outage banner both read
    # this; a broken backend must stop claiming to be healthy.
    monkeypatch.setattr(db, "ping", lambda: False)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"error": "database unavailable"}


def test_a_machine_fault_is_a_500_not_a_400(raising_client, monkeypatch):
    # A 400 sends a school off to hand-key results; a database that fell over
    # mid-write has to say "retry later" instead.
    def explode(_rows):
        raise RuntimeError("connection reset by peer")

    monkeypatch.setattr(db, "upsert_results", explode)
    response = post_xml(raising_client, single_result("1234", "1001", 20, 13))
    assert response.status_code == 500
    assert response.json() == {"error": "Internal server error"}


def test_a_machine_fault_leaks_no_internal_detail(raising_client, monkeypatch):
    def explode(_rows):
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(db, "upsert_results", explode)
    response = post_xml(raising_client, single_result("1234", "1001", 20, 13))
    assert "hunter2" not in response.text
    assert "db.internal" not in response.text


def test_a_body_that_lies_about_its_length_is_still_capped(client, monkeypatch):
    # Without Content-Length the size guard cannot fire up front, so the
    # streaming read has to stop on its own rather than buffer the lot.
    monkeypatch.setattr("app.main.MAX_BODY_BYTES", 1024)

    def chunks():
        for _ in range(16):
            yield b"x" * 512

    response = client.post("/import", content=chunks(), headers=MARKR)
    assert response.status_code == 400
    assert "large" in response.json()["error"]


def test_a_streamed_body_under_the_cap_still_imports(client, monkeypatch):
    monkeypatch.setattr("app.main.MAX_BODY_BYTES", 1024)
    body = single_result("1234", "1001", 20, 13)
    assert len(body) < 1024

    def chunks():
        yield body

    response = client.post("/import", content=chunks(), headers=MARKR)
    assert response.status_code == 200
    assert response.json() == {"imported": 1}


def test_dashboard_returns_both_structures_from_one_read(client):
    post_xml(client, FIXTURES.joinpath("sample_results.xml").read_bytes())
    response = client.get("/results/9863/dashboard")
    assert response.status_code == 200
    body = response.json()
    # Same shapes as the single-purpose endpoints, from one row set.
    assert body["aggregate"] == client.get("/results/9863/aggregate").json()
    assert body["histogram"] == client.get("/results/9863/histogram").json()
    assert body["aggregate"]["count"] == body["histogram"]["total"] == 81


def test_dashboard_counts_are_consistent_by_construction(client, monkeypatch):
    # The point of the endpoint: however many reads race an import, both
    # structures come from the one statistics statement.
    post_xml(client, single_result("1234", "1001", 20, 13))
    calls = 0
    real_fetch = db.fetch_dashboard

    def counting_fetch(test_id):
        nonlocal calls
        calls += 1
        return real_fetch(test_id)

    monkeypatch.setattr(db, "fetch_dashboard", counting_fetch)
    body = client.get("/results/1234/dashboard").json()
    assert calls == 1
    assert body["aggregate"]["count"] == body["histogram"]["total"] == 1


def test_dashboard_unknown_test_is_404(client):
    response = client.get("/results/nope/dashboard")
    assert response.status_code == 404
    assert response.json() == {"error": "Not found"}


def test_route_unsafe_test_id_rejects_the_document(client):
    # 'year/12' would be stored as a row no read endpoint could ever address:
    # the encoded slash is re-split by ASGI path decoding before routing.
    response = post_xml(client, single_result("year/12", "1001", 20, 13))
    assert response.status_code == 400
    assert "test-id" in response.json()["error"]
    assert stored_rows() == []


def test_leading_zero_ids_sort_numerically(client):
    post_xml(client, single_result("0001", "1", 10, 5))
    post_xml(client, single_result("10", "1", 10, 5))
    post_xml(client, single_result("2", "1", 10, 5))
    body = client.get("/tests").json()
    assert [t["test_id"] for t in body["tests"]] == ["0001", "2", "10"]


def test_read_endpoints_forbid_stale_caching(client):
    post_xml(client, single_result("1234", "1001", 20, 13))
    for path in ("/tests", "/results/1234/aggregate", "/results/1234/histogram"):
        assert client.get(path).headers["cache-control"] == "no-store"
    # The dashboard says no-cache instead: browsers may store it but must
    # revalidate, which is what routes them onto the 304 path.
    assert client.get("/results/1234/dashboard").headers["cache-control"] == "no-cache"


def test_dashboard_etag_answers_304_until_results_change(client):
    post_xml(client, single_result("1234", "1001", 20, 13))
    first = client.get("/results/1234/dashboard")
    etag = first.headers["etag"]

    unchanged = client.get(
        "/results/1234/dashboard", headers={"If-None-Match": etag}
    )
    assert unchanged.status_code == 304
    assert unchanged.headers["etag"] == etag

    post_xml(client, single_result("1234", "1002", 20, 17))
    changed = client.get(
        "/results/1234/dashboard", headers={"If-None-Match": etag}
    )
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag
    assert changed.json()["aggregate"]["count"] == 2


def test_idempotent_reimport_keeps_the_etag_stable(client):
    # No rows change, so the version must not move and every polling
    # dashboard keeps riding the 304 path.
    body = FIXTURES.joinpath("sample_results.xml").read_bytes()
    post_xml(client, body)
    etag = client.get("/results/9863/dashboard").headers["etag"]
    post_xml(client, body)
    response = client.get(
        "/results/9863/dashboard", headers={"If-None-Match": etag}
    )
    assert response.status_code == 304


def test_sql_statistics_match_the_reference_implementation(client):
    # Edge-heavy spread: 0%, exact bin boundaries, 100%, mixed denominators.
    from app.stats import aggregate_stats, histogram_bins

    marks = [(0, 20), (8, 20), (8, 10), (13, 20), (20, 20), (7, 10), (9, 30)]
    for i, (obtained, available) in enumerate(marks):
        post_xml(client, single_result("7777", str(3000 + i), available, obtained))

    rows = db.fetch_results("7777")
    body = client.get("/results/7777/dashboard").json()
    assert body["aggregate"] == aggregate_stats(rows)
    assert body["histogram"] == histogram_bins(rows)


def test_summary_backfill_restores_a_pre_summary_volume(client):
    # A volume written before test_summaries existed must list correctly
    # after one startup.
    post_xml(client, single_result("1234", "1001", 20, 13))
    with db.engine().begin() as conn:
        conn.execute(sa.text("TRUNCATE test_summaries"))
    assert client.get("/tests").json() == {"tests": []}

    db.init(attempts=1)  # what a restart runs
    listed = client.get("/tests").json()["tests"]
    assert [t["test_id"] for t in listed] == ["1234"]
    assert listed[0]["student_count"] == 1


def test_startup_reconciles_a_summary_an_older_version_left_wrong(client):
    # An upgrade from a version with the summary race must correct damaged
    # counts on its first boot, and move the version so ETags refresh.
    post_xml(client, single_result("1234", "1001", 20, 13))
    post_xml(client, single_result("1234", "1002", 20, 15))
    with db.engine().begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE test_summaries SET student_count = 1 "
                "WHERE test_id = '1234'"
            )
        )
    stale_etag = client.get("/results/1234/dashboard").headers["etag"]

    db.init(attempts=1)  # what the upgraded deployment runs at startup
    listed = client.get("/tests").json()["tests"]
    assert listed[0]["student_count"] == 2
    fresh = client.get(
        "/results/1234/dashboard", headers={"If-None-Match": stale_etag}
    )
    assert fresh.status_code == 200  # the corrected summary re-tagged


def test_routine_restarts_leave_versions_alone(client):
    # Reconciliation must be a no-op on healthy data, or every deploy would
    # invalidate every dashboard's ETag at once.
    post_xml(client, single_result("1234", "1001", 20, 13))
    etag = client.get("/results/1234/dashboard").headers["etag"]
    db.init(attempts=1)
    db.init(attempts=1)
    response = client.get(
        "/results/1234/dashboard", headers={"If-None-Match": etag}
    )
    assert response.status_code == 304


def test_import_notifies_listeners_on_commit(client):
    import time as _time

    import psycopg

    dsn = db.database_url().replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"LISTEN {db.NOTIFY_CHANNEL}")
        post_xml(client, single_result("1234", "1001", 20, 13))
        deadline = _time.time() + 5
        received = []
        while _time.time() < deadline and not received:
            gen = conn.notifies(timeout=0.5)
            received.extend(n.payload for n in gen)
        assert "1234" in received

        # An idempotent re-import must stay silent.
        post_xml(client, single_result("1234", "1001", 20, 13))
        quiet = list(conn.notifies(timeout=1.0))
        assert quiet == []



def test_dashboard_guards_against_a_vanishing_test(client, monkeypatch):
    # Defensive branch: a version row without result rows cannot happen
    # today (nothing deletes), so it is pinned here instead.
    monkeypatch.setattr(db, "fetch_freshness", lambda _id: (7, 1.0))
    monkeypatch.setattr(db, "fetch_dashboard", lambda _id: None)
    response = client.get("/results/1234/dashboard")
    assert response.status_code == 404
    assert response.json() == {"error": "Not found"}


def test_concurrent_imports_keep_maxima_and_exact_counts(client):
    """The brief's grading machines POST at the same time.

    Eight threads import interleaved documents that share forty students
    (listed in opposite orders, which would deadlock without deterministic
    lock ordering) and each add five students of their own (which would
    leave a stale summary count without lock-then-recompute).
    """
    from concurrent.futures import ThreadPoolExecutor

    from app.ingest import parse_document

    def doc(students):
        records = "".join(
            f"<mcq-test-result><student-number>{num}</student-number>"
            f"<test-id>ct</test-id>"
            f'<summary-marks available="{avail}" obtained="{obt}" />'
            f"</mcq-test-result>"
            for num, avail, obt in students
        )
        return f"<mcq-test-results>{records}</mcq-test-results>".encode()

    shared = [f"s{i:03d}" for i in range(40)]
    docs = []
    for wave in range(8):
        order = shared if wave % 2 == 0 else list(reversed(shared))
        rescans = [(num, 20 + wave, wave) for num in order]
        fresh = [(f"x{wave}-{i}", 50, 25) for i in range(5)]
        docs.append(doc(rescans + fresh))

    with ThreadPoolExecutor(max_workers=8) as pool:
        # A deadlock or stale write surfaces here as a raised exception or
        # below as a wrong number; pool.map re-raises worker errors.
        list(pool.map(lambda raw: db.upsert_results(parse_document(raw).rows), docs))

    rows = {
        num: (avail, obt)
        for num, avail, obt in (
            (r[1], r[2], r[3]) for r in stored_rows()
        )
    }
    assert len(rows) == 45 * 8 - 40 * 7  # 40 shared + 40 unique
    for num in shared:
        # Maxima merged independently across all eight waves.
        assert rows[num] == (27, 7)

    listing = client.get("/tests").json()["tests"]
    assert listing == [
        {"test_id": "ct", "student_count": 80, "marks_available": 50}
    ]
    body = client.get("/results/ct/dashboard").json()
    assert body["aggregate"]["count"] == body["histogram"]["total"] == 80


def test_etag_cannot_collide_across_database_rebuilds(client):
    # Versions restart at the same numbers in a rebuilt database. A browser
    # holding an ETag from the previous database must get fresh data, never
    # a 304 that pins its cache to scores that no longer exist.
    post_xml(client, single_result("1234", "1001", 20, 2))  # 10%
    old_etag = client.get("/results/1234/dashboard").headers["etag"]

    # Simulate `docker compose down -v` plus re-import.
    with db.engine().begin() as conn:
        conn.execute(sa.text("TRUNCATE student_results, test_summaries"))
    post_xml(client, single_result("1234", "1001", 20, 18))  # 90%

    response = client.get(
        "/results/1234/dashboard", headers={"If-None-Match": old_etag}
    )
    assert response.status_code == 200
    assert response.headers["etag"] != old_etag
    assert response.json()["aggregate"]["mean"] == 90.0
