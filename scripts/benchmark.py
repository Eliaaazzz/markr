"""Repeatable load generator behind the README's performance numbers.

Standard library only. Every invocation uses a unique test-id namespace and
verifies the rows that reached PostgreSQL, so a second run cannot silently
measure the idempotent path while labelling it fresh write throughput.

    python scripts/benchmark.py                 # http://localhost:4567
    python scripts/benchmark.py http://host:4567
    python scripts/benchmark.py --run-id review-1
"""

import argparse
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://localhost:4567"
SAMPLE = Path(__file__).resolve().parent.parent / "sample_results.xml"
MARKR_TYPE = "text/xml+markr"


def call(method, path, body=None, ctype=None, etag=None):
    request = urllib.request.Request(BASE + path, data=body, method=method)
    if ctype:
        request.add_header("Content-Type", ctype)
    if etag:
        request.add_header("If-None-Match", etag)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
            status, header = response.status, response.headers.get("ETag")
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        status, header = exc.code, exc.headers.get("ETag")
    return (time.perf_counter() - started) * 1000, status, header, payload


def decoded(result, label):
    try:
        return json.loads(result[3])
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"{label}: response was not valid JSON") from exc


def require_status(result, expected, label):
    if result[1] != expected:
        raise RuntimeError(f"{label}: expected HTTP {expected}, got {result[1]}")


def imported(result, expected):
    try:
        return result[1] == 200 and json.loads(result[3]).get("imported") == expected
    except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
        return False


def run(
    label,
    concurrency,
    total,
    make_call,
    ok_status=200,
    validator=None,
    warmup=True,
    units_per_call=1,
):
    def valid(result):
        return result[1] == ok_status and (
            validator is None or validator(result)
        )

    if warmup:
        warm = make_call(-1)
        if not valid(warm):
            raise RuntimeError(f"{label}: warm-up request failed validation")
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        started = time.perf_counter()
        results = list(pool.map(make_call, range(total)))
        elapsed = time.perf_counter() - started
    latencies = sorted(result[0] for result in results)
    errors = sum(1 for result in results if not valid(result))
    pick = lambda q: latencies[min(int(len(latencies) * q), len(latencies) - 1)]
    qps = total / elapsed
    rate = qps * units_per_call
    suffix = f"  students/s={rate:9.1f}" if units_per_call != 1 else ""
    print(
        f"{label:<28} c={concurrency:<3} qps={qps:8.1f}{suffix}  "
        f"p50={pick(0.5):7.1f}ms  p95={pick(0.95):7.1f}ms  errors={errors}"
    )
    if errors:
        raise RuntimeError(f"{label}: {errors} request(s) failed validation")
    return rate


def synthetic(test_id, students, marks=20, start=0):
    records = "".join(
        f"<mcq-test-result><student-number>{start + i:09d}</student-number>"
        f"<test-id>{test_id}</test-id>"
        f'<summary-marks available="{marks}" obtained="{i % (marks + 1)}" />'
        f"</mcq-test-result>"
        for i in range(students)
    )
    return f"<mcq-test-results>{records}</mcq-test-results>".encode()


def sample_for(test_id):
    source = SAMPLE.read_bytes()
    marker = b"<test-id>9863</test-id>"
    if marker not in source:
        raise RuntimeError("sample fixture no longer contains test id 9863")
    replacement = f"<test-id>{test_id}</test-id>".encode()
    return source.replace(marker, replacement)


def fetch_json(path, label):
    result = call("GET", path)
    require_status(result, 200, label)
    return decoded(result, label)


def verify_count(test_id, expected):
    aggregate = fetch_json(
        f"/results/{test_id}/aggregate", f"aggregate verification for {test_id}"
    )
    listing = fetch_json("/tests", f"test-list verification for {test_id}")
    summary = next(
        (item for item in listing.get("tests", []) if item.get("test_id") == test_id),
        None,
    )
    aggregate_count = aggregate.get("count")
    summary_count = None if summary is None else summary.get("student_count")
    if aggregate_count != expected or summary_count != expected:
        raise RuntimeError(
            f"{test_id}: expected {expected} stored students, "
            f"aggregate reported {aggregate_count}, /tests reported {summary_count}"
        )
    print(f"  verified {test_id}: {expected:,} stored students")


def ensure_absent(test_ids):
    for test_id in test_ids:
        result = call("GET", f"/results/{test_id}/aggregate")
        if result[1] != 404:
            raise RuntimeError(
                f"run namespace collision: test id {test_id!r} already exists"
            )


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", nargs="?", default="http://localhost:4567")
    parser.add_argument(
        "--run-id",
        help="safe unique namespace (generated automatically when omitted)",
    )
    args = parser.parse_args()
    if args.run_id is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        args.run_id = f"{stamp}-{secrets.token_hex(4)}"
    if not re.fullmatch(r"[A-Za-z0-9._~-]{1,32}", args.run_id):
        parser.error("--run-id must be 1-32 URL-safe characters")
    return args


def main():
    global BASE
    args = arguments()
    BASE = args.base.rstrip("/")
    prefix = f"bench-{args.run_id}"
    ids = {
        "sample": f"{prefix}-sample",
        "large": f"{prefix}-large",
        "c1": f"{prefix}-ingest-c1",
        "c2": f"{prefix}-ingest-c2",
        "c4": f"{prefix}-ingest-c4",
    }
    ensure_absent(ids.values())

    sample = sample_for(ids["sample"])
    sample_import = call("POST", "/import", sample, MARKR_TYPE)
    if not imported(sample_import, 100):
        raise RuntimeError("sample import did not accept all 100 records")
    verify_count(ids["sample"], 81)

    print(f"target {BASE}")
    print(f"run id {args.run_id}\n")
    print("dashboard reads, 81-student test")
    sample_path = f"/results/{ids['sample']}/dashboard"
    for concurrency in (1, 8, 32):
        run(
            "  200 full body",
            concurrency,
            400,
            lambda _index: call("GET", sample_path),
        )
    etag_result = call("GET", sample_path)
    require_status(etag_result, 200, "81-student ETag lookup")
    etag = etag_result[2]
    if etag is None:
        raise RuntimeError("81-student dashboard returned no ETag")
    for concurrency in (1, 32):
        run(
            "  304 unchanged",
            concurrency,
            600,
            lambda _index: call("GET", sample_path, etag=etag),
            ok_status=304,
        )

    print("\ndashboard reads, 10,000-student test")
    large_body = synthetic(ids["large"], 10_000)
    large_import = call("POST", "/import", large_body, MARKR_TYPE)
    if not imported(large_import, 10_000):
        raise RuntimeError("10,000-student import failed validation")
    print(
        f"  (import of 10,000 students: {large_import[0]:.0f}ms, "
        f"status {large_import[1]})"
    )
    verify_count(ids["large"], 10_000)
    large_path = f"/results/{ids['large']}/dashboard"
    for concurrency in (1, 8, 32):
        run(
            "  200 full body",
            concurrency,
            200,
            lambda _index: call("GET", large_path),
        )
    etag_result = call("GET", large_path)
    require_status(etag_result, 200, "10,000-student ETag lookup")
    etag10 = etag_result[2]
    if etag10 is None:
        raise RuntimeError("10,000-student dashboard returned no ETag")
    run(
        "  304 unchanged",
        32,
        400,
        lambda _index: call("GET", large_path, etag=etag10),
        ok_status=304,
    )

    print("\nimport throughput, 100 verified-new students per document")
    for concurrency in (1, 2, 4):
        test_id = ids[f"c{concurrency}"]
        bodies = [
            synthetic(test_id, 100, start=batch * 100) for batch in range(100)
        ]
        run(
            "  POST /import",
            concurrency,
            len(bodies),
            lambda index: call("POST", "/import", bodies[index], MARKR_TYPE),
            validator=lambda result: imported(result, 100),
            warmup=False,
            units_per_call=100,
        )
        verify_count(test_id, 10_000)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
