"""Offline tests for the matplotlib plotting layer (skipped if matplotlib absent)."""

import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

import pandas as pd  # noqa: E402

from scopusflow.plots import plot_comparison, plot_top, plot_trend  # noqa: E402


def test_plot_trend_returns_an_axes():
    trend = pd.DataFrame({"year": [2018, 2019, 2020], "n": [3, 5, 4]})
    ax = plot_trend(trend)
    assert isinstance(ax, matplotlib.axes.Axes)


def test_plot_top_returns_an_axes_with_expected_bars():
    top = pd.DataFrame({"value": ["Nature", "Cell", "Science"], "n": [9, 5, 2]})
    ax = plot_top(top)
    assert isinstance(ax, matplotlib.axes.Axes)
    assert len(ax.patches) == 3


def _comparison_frame(n_topics):
    """A minimal comparison frame with enough topics to force a legend."""
    years = [2018, 2019, 2020]
    rows = [
        {"query": "ref", "query_type": "reference", "abridged_query": "reference",
         "year": year, "n": 100, "reference_n": 100,
         "comparison_percentage": 100.0, "average_comparison_percentage": 100.0}
        for year in years
    ]
    for t in range(n_topics):
        for year in years:
            rows.append({
                "query": f"topic {t}", "query_type": "comparison",
                "abridged_query": f"topic {t}", "year": year, "n": 10 + t,
                "reference_n": 100, "comparison_percentage": float(10 + t),
                "average_comparison_percentage": float(10 + t),
            })
    return pd.DataFrame(rows)


def test_plot_comparison_accepts_legend_inside():
    # Many topics so a legend is drawn rather than direct line labels.
    cmp = _comparison_frame(n_topics=10)
    ax = plot_comparison(cmp, legend_inside=True)
    assert isinstance(ax, matplotlib.axes.Axes)
    assert ax.get_legend() is not None
