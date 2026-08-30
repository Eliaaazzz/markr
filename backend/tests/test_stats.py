"""Unit tests for the statistics functions, all pure Python."""

from app.stats import aggregate_stats, histogram_bins


def test_single_result_matches_the_brief_example():
    # 13/20 is the Jane Austen record: every statistic collapses to 65.0
    assert aggregate_stats([(13, 20)]) == {
        "mean": 65.0,
        "stddev": 0.0,
        "min": 65.0,
        "max": 65.0,
        "p25": 65.0,
        "p50": 65.0,
        "p75": 65.0,
        "count": 1,
    }


def test_quartiles_use_r7_linear_interpolation():
    stats = aggregate_stats([(1, 10), (2, 10), (3, 10), (4, 10)])
    assert stats["p25"] == 17.5
    assert stats["p50"] == 25.0
    assert stats["p75"] == 32.5


def test_mean_and_population_stddev():
    stats = aggregate_stats([(0, 10), (10, 10)])
    assert stats["mean"] == 50.0
    assert stats["stddev"] == 50.0
    assert stats["min"] == 0.0
    assert stats["max"] == 100.0
    assert stats["count"] == 2


def test_percentages_use_each_students_own_available_marks():
    stats = aggregate_stats([(5, 10), (10, 20)])
    assert stats["mean"] == 50.0


def test_values_round_to_two_decimals():
    assert aggregate_stats([(1, 3)])["mean"] == 33.33


def test_histogram_bin_edges():
    rows = [
        (0, 10),  # 0%     -> first bin
        (8999, 10000),  # 89.99% -> ninth bin
        (9, 10),  # 90%    -> last bin (closed lower edge)
        (10, 10),  # 100%   -> last bin (closed upper edge)
    ]
    histogram = histogram_bins(rows)
    counts = [b["count"] for b in histogram["bins"]]
    assert counts == [1, 0, 0, 0, 0, 0, 0, 0, 1, 2]
    assert histogram["total"] == 4


def test_histogram_always_has_ten_bins_with_fixed_edges():
    histogram = histogram_bins([(13, 20)])
    assert len(histogram["bins"]) == 10
    assert histogram["bins"][0] == {"lower_pct": 0, "upper_pct": 10, "count": 0}
    assert histogram["bins"][6] == {"lower_pct": 60, "upper_pct": 70, "count": 1}
    assert histogram["bins"][9] == {"lower_pct": 90, "upper_pct": 100, "count": 0}
