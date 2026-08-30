"""Load generator behind the README's performance numbers.

Standard library only. Run it against a stack that is up, from the repo root:

    python scripts/benchmark.py                 # http://localhost:4567
    python scripts/benchmark.py http://host:4567

It imports the sample file, measures the dashboard read and its 304 path at
two test sizes (81 students and a synthetic 10,000), then measures import
throughput. Numbers vary with hardware; the shape is the point. The 10,000
student rows land under test id 'loadtest'; wipe them afterwards with
`docker compose down -v` or leave them, nothing else reads that id.
"""

import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:4567"
SAMPLE = Path(__file__).resolve().parent.parent / "sample_results.xml"


def call(method, path, body=None, ctype=None, etag=None):
    request = urllib.request.Request(BASE + path, data=body, method=method)
    if ctype:
        request.add_header("Content-Type", ctype)
    if etag:
        request.add_header("If-None-Match", etag)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response.read()
            status, header = response.status, response.headers.get("ETag")
    except urllib.error.HTTPError as exc:
        exc.read()
        status, header = exc.code, exc.headers.get("ETag")
    return (time.perf_counter() - started) * 1000, status, header


def run(label, concurrency, total, make_call, ok_status=200):
    make_call()  # warm the connection pool outside the sample
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        started = time.perf_counter()
        results = list(pool.map(lambda _: make_call(), range(total)))
        elapsed = time.perf_counter() - started
    latencies = sorted(r[0] for r in results)
    errors = sum(1 for r in results if r[1] != ok_status)
    pick = lambda q: latencies[min(int(len(latencies) * q), len(latencies) - 1)]
    print(
        f"{label:<28} c={concurrency:<3} qps={total / elapsed:8.1f}  "
        f"p50={pick(0.5):7.1f}ms  p95={pick(0.95):7.1f}ms  errors={errors}"
    )


def synthetic(test_id, students, marks=20):
    records = "".join(
        f"<mcq-test-result><student-number>{i:09d}</student-number>"
        f"<test-id>{test_id}</test-id>"
        f'<summary-marks available="{marks}" obtained="{i % (marks + 1)}" />'
        f"</mcq-test-result>"
        for i in range(students)
    )
    return f"<mcq-test-results>{records}</mcq-test-results>".encode()


def main():
    sample = SAMPLE.read_bytes()
    call("POST", "/import", sample, "text/xml+markr")

    print(f"target {BASE}\n")
    print("dashboard reads, 81-student test")
    for concurrency in (1, 8, 32):
        run("  200 full body", concurrency, 400,
            lambda: call("GET", "/results/9863/dashboard"))
    _, _, etag = call("GET", "/results/9863/dashboard")
    for concurrency in (1, 32):
        run("  304 unchanged", concurrency, 600,
            lambda: call("GET", "/results/9863/dashboard", etag=etag),
            ok_status=304)

    print("\ndashboard reads, 10,000-student test")
    ms, status, _ = call("POST", "/import", synthetic("loadtest", 10_000),
                         "text/xml+markr")
    print(f"  (import of 10,000 students: {ms:.0f}ms, status {status})")
    for concurrency in (1, 8, 32):
        run("  200 full body", concurrency, 200,
            lambda: call("GET", "/results/loadtest/dashboard"))
    _, _, etag10 = call("GET", "/results/loadtest/dashboard")
    run("  304 unchanged", 32, 400,
        lambda: call("GET", "/results/loadtest/dashboard", etag=etag10),
        ok_status=304)

    print("\nimport throughput, 100 fresh students per document")
    # Every document carries students nobody has seen before, so this
    # measures sustained real writes, never the idempotent skip path.
    counter = iter(range(10_000_000, 20_000_000, 100))

    def fresh_import():
        base = next(counter)
        records = "".join(
            f"<mcq-test-result><student-number>{base + i}</student-number>"
            f"<test-id>ingest-bench</test-id>"
            f'<summary-marks available="20" obtained="{i % 21}" />'
            f"</mcq-test-result>"
            for i in range(100)
        )
        body = f"<mcq-test-results>{records}</mcq-test-results>".encode()
        return call("POST", "/import", body, "text/xml+markr")

    for concurrency in (1, 2, 4):
        run("  POST /import", concurrency, 100, fresh_import)


if __name__ == "__main__":
    main()
