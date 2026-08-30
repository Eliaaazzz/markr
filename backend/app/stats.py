"""Reference implementation of the statistics, used by the test suite.

The serving path computes these same numbers in one SQL statement (see
db.fetch_dashboard); the suite cross-checks that statement against this
plain-Python version, so the arithmetic is pinned in two independent ways.
"""

from collections.abc import Sequence
from statistics import StatisticsError, fmean, pstdev, quantiles

MarkPair = tuple[int, int]  # (marks_obtained, marks_available)


def _percentages(rows: Sequence[MarkPair]) -> list[float]:
    return [obtained / available * 100 for obtained, available in rows]


def aggregate_stats(rows: Sequence[MarkPair]) -> dict:
    """The eight dashboard numbers for a non-empty result set.

    stddev is the population form (a lone result has spread 0.0, per the
    brief's worked example) and quartiles use R-7 linear interpolation, the
    numpy/spreadsheet default.
    """
    pcts = _percentages(rows)
    try:
        p25, p50, p75 = quantiles(pcts, n=4, method="inclusive")
    except StatisticsError:  # a single data point is its own quartiles
        p25 = p50 = p75 = pcts[0]
    return {
        "mean": round(fmean(pcts), 2),
        "stddev": round(pstdev(pcts), 2),
        "min": round(min(pcts), 2),
        "max": round(max(pcts), 2),
        "p25": round(p25, 2),
        "p50": round(p50, 2),
        "p75": round(p75, 2),
        "count": len(pcts),
    }


def histogram_bins(rows: Sequence[MarkPair]) -> dict:
    """Ten fixed ten-point bins; the last is closed so 100% lands in [90, 100]."""
    counts = [0] * 10
    pcts = _percentages(rows)
    for pct in pcts:
        counts[min(int(pct // 10), 9)] += 1
    return {
        "bins": [
            {"lower_pct": i * 10, "upper_pct": (i + 1) * 10, "count": counts[i]}
            for i in range(10)
        ],
        "total": len(pcts),
    }
