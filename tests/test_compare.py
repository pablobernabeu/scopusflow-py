"""Offline tests for topic comparison (pure assembly, Wilson band, plot)."""

import pandas as pd
import pytest

from scopusflow.compare import _assemble, _comparison_block, compare_topics
from scopusflow.plots import _wilson


def test_comparison_block_percentages_and_average():
    rows = _comparison_block("q", "comparison", "term", [2018, 2019],
                             {2018: 20, 2019: 40}, {2018: 100, 2019: 100})
    assert [r["comparison_percentage"] for r in rows] == [20.0, 40.0]
    # average rests on period totals: 100 * (60 / 200)
    assert rows[0]["average_comparison_percentage"] == 30.0


def test_comparison_block_missing_reference_yields_none():
    rows = _comparison_block("q", "comparison", "t", [2020], {2020: 5}, {2020: 0})
    assert rows[0]["comparison_percentage"] is None
    assert rows[0]["average_comparison_percentage"] is None


def test_assemble_sorts_reference_first_then_descending_average():
    df = _assemble("ref", "refq", {2020: 100},
                   [("low", "ql", {2020: 5}), ("high", "qh", {2020: 40})], [2020])
    assert df.iloc[0]["query_type"] == "reference"
    comp = df[df["query_type"] == "comparison"]
    assert list(comp["abridged_query"]) == ["high", "low"]


def test_compare_topics_validates_input():
    with pytest.raises(ValueError):
        compare_topics("", ["x"], [2020])
    with pytest.raises(ValueError):
        compare_topics("ref", [], [2020])
    with pytest.raises(ValueError):
        compare_topics("ref", ["  "], [2020])
    with pytest.raises(ValueError):
        compare_topics("ref", ["x"], [])
    with pytest.raises(ValueError):
        compare_topics("ref", ["x"], None)        # None years -> ValueError, not TypeError
    with pytest.raises(ValueError):
        compare_topics("ref", ["x"], [2020.5])     # non-whole year rejected
    with pytest.raises(ValueError):
        compare_topics("ref", ["x"], [1500])       # out-of-range year rejected


def test_wilson_is_bounded_and_clipped():
    lower, upper = _wilson([20], [100])
    assert 0 <= lower[0] < 20 < upper[0] <= 100
    lo0, _ = _wilson([0], [10])
    assert lo0[0] == 0.0


def _comparison_frame():
    return pd.DataFrame({
        "query": ["q"] * 4, "query_type": ["comparison"] * 4,
        "abridged_query": ["cv", "cv", "dd", "dd"],
        "year": [2019, 2020, 2019, 2020], "n": [20, 30, 5, 8],
        "reference_n": [100, 100, 100, 100],
        "comparison_percentage": [20.0, 30.0, 5.0, 8.0],
        "average_comparison_percentage": [25.0, 25.0, 6.5, 6.5],
    })


def test_plot_comparison_returns_axes():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    from scopusflow.plots import plot_comparison

    ax = plot_comparison(_comparison_frame())
    assert ax is not None
    assert ax.get_ylabel().startswith("Share")


def test_plot_comparison_highlight_and_validation():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    from scopusflow.plots import plot_comparison

    plot_comparison(_comparison_frame(), highlight="cv")
    with pytest.raises(ValueError):
        plot_comparison(_comparison_frame(), highlight="nope")
    with pytest.raises(ValueError):
        plot_comparison(pd.DataFrame({"a": [1]}))
