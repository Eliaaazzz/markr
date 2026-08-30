"""Compare the original Python aggregation path with the serving SQL path.

The two paths read the same test from the same PostgreSQL instance. Their
payloads must match before timings are reported.
"""

import argparse
import math
import secrets
import time

from app import db
from app.ingest import StudentResult
from app.stats import aggregate_stats, histogram_bins


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def before_path(test_id: str) -> dict:
    """Fetch every mark pair, then calculate the dashboard in Python."""
    rows = db.fetch_results(test_id)
    return {
        "aggregate": aggregate_stats(rows),
        "histogram": histogram_bins(rows),
    }


def after_path(test_id: str) -> dict | None:
    """Let PostgreSQL calculate the dashboard and return one aggregate row."""
    return db.fetch_dashboard(test_id)


def timed(call) -> tuple[float, dict | None]:
    started = time.perf_counter()
    payload = call()
    return (time.perf_counter() - started) * 1_000, payload


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--students", type=int, default=10_000)
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--warmups", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.students <= 10_000:
        parser.error("--students must be between 1 and 10,000")
    if args.runs < 1:
        parser.error("--runs must be positive")
    if args.warmups < 0:
        parser.error("--warmups cannot be negative")
    return args


def main() -> None:
    args = arguments()
    test_id = f"query-compare-{secrets.token_hex(6)}"
    rows = [
        StudentResult(
            test_id=test_id,
            student_number=f"{index:09d}",
            first_name=None,
            last_name=None,
            marks_available=100,
            marks_obtained=(index * 37) % 101,
            scanned_at=None,
        )
        for index in range(args.students)
    ]

    db.init()
    try:
        written = db.upsert_results(rows)
        if written != args.students:
            raise RuntimeError(
                f"seed wrote {written:,} rows; expected {args.students:,}"
            )

        expected = before_path(test_id)
        actual = after_path(test_id)
        if actual != expected:
            raise RuntimeError("Python and SQL paths produced different dashboards")

        for _ in range(args.warmups):
            if before_path(test_id) != expected or after_path(test_id) != expected:
                raise RuntimeError("a warm-up returned an unexpected dashboard")

        before_ms: list[float] = []
        after_ms: list[float] = []
        paths = (
            ("before", lambda: before_path(test_id), before_ms),
            ("after", lambda: after_path(test_id), after_ms),
        )
        for index in range(args.runs):
            ordered_paths = paths if index % 2 == 0 else tuple(reversed(paths))
            for label, call, samples in ordered_paths:
                elapsed, payload = timed(call)
                if payload != expected:
                    raise RuntimeError(f"{label} path returned an unexpected dashboard")
                samples.append(elapsed)

        before_p50 = percentile(before_ms, 0.50)
        before_p95 = percentile(before_ms, 0.95)
        after_p50 = percentile(after_ms, 0.50)
        after_p95 = percentile(after_ms, 0.95)

        print(
            f"query path comparison: {args.students:,} students, "
            f"{args.runs} measured runs per path"
        )
        print("payloads match: yes")
        print(
            f"before  fetch {args.students:,} rows + Python stats  "
            f"p50={before_p50:.2f}ms  p95={before_p95:.2f}ms"
        )
        print(
            "after   one SQL aggregate row             "
            f"p50={after_p50:.2f}ms  p95={after_p95:.2f}ms"
        )
        print(
            f"speedup                                      "
            f"p50={before_p50 / after_p50:.2f}x  "
            f"p95={before_p95 / after_p95:.2f}x"
        )
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
