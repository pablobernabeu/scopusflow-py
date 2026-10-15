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


def test_plot_trend_rejects_an_empty_trend_by_name():
    # An empty frame used to fail inside numpy with "ufunc 'isfinite' not
    # supported". The message is the R twin's.
    with pytest.raises(ValueError, match="^The trend has no years to plot.$"):
        plot_trend(pd.DataFrame({"year": [], "n": []}))


def test_plot_trend_draws_a_year_without_records_at_zero():
    from scopusflow.trend import year_counts

    ax = plot_trend(year_counts(pd.DataFrame({"year": [2017, 2017, 2019]})))
    x, y = ax.lines[0].get_data()
    assert list(x) == [2017, 2018, 2019]
    assert list(y) == [2, 0, 1]


def _notes(ax):
    return [t.get_text() for t in ax.texts if "incomplete" in t.get_text()]


def test_plot_trend_says_when_its_last_year_was_still_being_indexed():
    trend = pd.DataFrame({"year": [2024, 2025, 2026], "n": [30, 40, 12]})
    # The note is read from the recorded retrieval time, never from the
    # session's clock, so a trend that records none carries no note.
    assert _notes(plot_trend(trend)) == []
    trend.attrs["retrieved_at"] = "2026-09-29T10:15:00+00:00"
    ax = plot_trend(trend)
    assert _notes(ax) == ["2026 was incomplete when retrieved on 2026-09-29."]
    # It sits below the axis label, where it covers neither the label nor the
    # tick labels.
    ax.figure.canvas.draw()
    note = next(t for t in ax.texts if "incomplete" in t.get_text())
    assert note.get_window_extent().y1 <= ax.xaxis.label.get_window_extent().y0
    # A span that ends before the year of retrieval carries no note.
    trend.attrs["retrieved_at"] = "2027-02-01T10:15:00+00:00"
    assert _notes(plot_trend(trend)) == []


def test_plot_top_returns_an_axes_with_expected_bars():
    top = pd.DataFrame({"value": ["Nature", "Cell", "Science"], "n": [9, 5, 2]})
    ax = plot_top(top)
    assert isinstance(ax, matplotlib.axes.Axes)
    assert len(ax.patches) == 3


def test_plot_top_count_labels_fit_inside_the_axes():
    top = pd.DataFrame({"value": ["Nature", "Cell"], "n": [12345, 5]})
    ax = plot_top(top)
    labels = [t for t in ax.texts if t.get_text() == "12,345"]
    assert labels, "the widest bar should carry a formatted count label"
    ax.figure.canvas.draw()
    assert labels[0].get_window_extent().x1 <= ax.get_window_extent().x1


def test_plot_top_rejects_an_empty_tally_by_name():
    # top() returns no rows for a record set whose publication column is all
    # missing; that used to surface as an opaque max() error on label widths.
    empty = pd.DataFrame({"value": [], "n": []})
    with pytest.raises(ValueError, match="no rows to plot"):
        plot_top(empty)


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
