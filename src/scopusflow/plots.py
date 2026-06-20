"""Minimal matplotlib visualisations for record summaries.

matplotlib is an optional dependency, imported lazily inside each function so the
rest of the package stays usable without it. Each plot accepts a ready-made
summary frame (from :mod:`scopusflow.trend` or :func:`scopusflow.records.top`)
and returns the matplotlib ``Axes`` for further customisation.
"""

from __future__ import annotations

import pandas as pd


def plot_trend(trend: pd.DataFrame, ax=None):
    """Plot publication counts over time as a filled area, line and points.

    ``trend`` has columns ``["year", "n"]``; returns the matplotlib ``Axes``.
    """
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots()

    years = trend["year"]
    counts = trend["n"]
    ax.fill_between(years, counts, alpha=0.2)
    ax.plot(years, counts)
    ax.scatter(years, counts)
    ax.set_xlabel("Year")
    ax.set_ylabel("Records")
    return ax


def plot_top(top: pd.DataFrame, ax=None):
    """Plot a horizontal bar chart of the most frequent values, largest on top.

    ``top`` has columns ``["value", "n"]`` (from :func:`scopusflow.records.top`);
    returns the matplotlib ``Axes``.
    """
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots()

    # Reverse so the largest count sits at the top of the chart.
    ordered = top.iloc[::-1]
    ax.barh(ordered["value"].astype(str), ordered["n"])
    ax.set_xlabel("Records")
    ax.set_ylabel("Value")
    return ax
