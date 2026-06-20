"""Offline tests for the matplotlib plotting layer (skipped if matplotlib absent)."""

import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

import pandas as pd  # noqa: E402

from scopusflow.plots import plot_top, plot_trend  # noqa: E402


def test_plot_trend_returns_an_axes():
    trend = pd.DataFrame({"year": [2018, 2019, 2020], "n": [3, 5, 4]})
    ax = plot_trend(trend)
    assert isinstance(ax, matplotlib.axes.Axes)


def test_plot_top_returns_an_axes_with_expected_bars():
    top = pd.DataFrame({"value": ["Nature", "Cell", "Science"], "n": [9, 5, 2]})
    ax = plot_top(top)
    assert isinstance(ax, matplotlib.axes.Axes)
    assert len(ax.patches) == 3
