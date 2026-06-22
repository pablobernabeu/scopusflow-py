"""Minimal matplotlib visualisations for record summaries.

matplotlib is an optional dependency, imported lazily inside each function so the
rest of the package stays usable without it. Each plot accepts a ready-made
summary frame (from :mod:`scopusflow.trend` or :func:`scopusflow.records.top`)
and returns the matplotlib ``Axes`` for further customisation.
"""

from __future__ import annotations

import math

import pandas as pd

#: Viridis-derived brand colours, matching the R package's plots.
_TREND_COLOUR = "#31688E"
_TOP_COLOUR = "#35B779"


def _clean_axes(ax) -> None:
    """Drop the top and right spines for a lighter, consistent look."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def plot_trend(trend: pd.DataFrame, ax=None):
    """Plot publication counts over time as a filled area, line and points.

    ``trend`` has columns ``["year", "n"]``; returns the matplotlib ``Axes``.
    """
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots()

    years = trend["year"]
    counts = trend["n"]
    ax.fill_between(years, counts, alpha=0.16, color=_TREND_COLOUR)
    ax.plot(years, counts, color=_TREND_COLOUR, linewidth=2)
    ax.scatter(years, counts, color=_TREND_COLOUR, s=18, zorder=3)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Year")
    ax.set_ylabel("Records")
    _clean_axes(ax)
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
    ax.barh(ordered["value"].astype(str), ordered["n"], color=_TOP_COLOUR)
    ax.set_xlabel("Records")
    ax.set_ylabel("")
    _clean_axes(ax)
    return ax


def _wilson(x, n, z: float = 1.96):
    """Wilson score interval on a binomial share, as percentages in [0, 100].
    ``x`` is the comparison count and ``n`` the reference count per year."""
    import numpy as np

    x = np.asarray(x, dtype=float)
    n = np.asarray(n, dtype=float)
    phat = x / n
    denom = 1 + z ** 2 / n
    centre = (phat + z ** 2 / (2 * n)) / denom
    margin = (z / denom) * np.sqrt(phat * (1 - phat) / n + z ** 2 / (4 * n ** 2))
    lower = np.clip((centre - margin) * 100, 0, 100)
    upper = np.clip((centre + margin) * 100, 0, 100)
    return lower, upper


def _spread_positions(values, gap: float):
    """Nudge label positions apart so none sits within ``gap`` of another, in
    their original order, moving each as little as possible (upwards). Used to
    keep direct end-labels legible where lines converge at the right edge."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    adjusted = list(values)
    for k in range(1, len(order)):
        i, prev = order[k], order[k - 1]
        if adjusted[i] < adjusted[prev] + gap:
            adjusted[i] = adjusted[prev] + gap
    return adjusted


def plot_comparison(comparison: pd.DataFrame, highlight=None, interval: bool = True,
                    ax=None):
    """Plot each comparison topic's share of the reference literature over time.

    ``comparison`` is the frame from :func:`scopusflow.compare.compare_topics`.
    With ``interval`` a shaded Wilson band shows how stable each yearly share is
    (illustrative, not a confidence interval — Scopus counts are exact).
    ``highlight`` names one topic to draw in an accent colour, the rest in grey.
    Returns the matplotlib ``Axes``.
    """
    import matplotlib.pyplot as plt

    required = {"query_type", "abridged_query", "year", "comparison_percentage"}
    if not required.issubset(comparison.columns):
        raise ValueError("comparison must be a topic-comparison frame.")

    df = comparison[comparison["query_type"] == "comparison"].copy()
    df = df[df["comparison_percentage"].notna()]
    if df.empty:
        raise ValueError("comparison has no comparison topics with a finite share to plot.")

    order = (df.groupby("abridged_query")["average_comparison_percentage"].first()
             .reset_index()
             .sort_values(["average_comparison_percentage", "abridged_query"],
                          ascending=[False, True]))
    topics = list(order["abridged_query"])
    if highlight is not None and highlight not in topics:
        raise ValueError(f"highlight must be one of: {', '.join(topics)}.")

    if ax is None:
        _, ax = plt.subplots()
    cmap = plt.get_cmap("viridis")
    spread = max(len(topics) - 1, 1)
    has_band = interval and {"n", "reference_n"}.issubset(df.columns)
    label_points = []

    for i, topic in enumerate(topics):
        sub = df[df["abridged_query"] == topic].sort_values("year")
        is_hi = highlight == topic
        if highlight is not None:
            colour = "#BB5566" if is_hi else "#BFBFBF"
            width = 1.6 if is_hi else 0.8
        else:
            colour = cmap(0.05 + 0.8 * i / spread)
            width = 1.4
        if has_band and (highlight is None or is_hi):
            lo, up = _wilson(sub["n"].to_numpy(), sub["reference_n"].to_numpy())
            ax.fill_between(sub["year"], lo, up, color=colour, alpha=0.16, linewidth=0)
        ax.plot(sub["year"], sub["comparison_percentage"], color=colour, linewidth=width)
        ax.scatter(sub["year"], sub["comparison_percentage"], color=colour, s=14, zorder=3)
        if len(topics) <= 6 or is_hi:
            last = sub.iloc[-1]
            label_points.append((float(last["year"]),
                                  float(last["comparison_percentage"]), topic, colour))

    # Cap the y-axis at the next 5% above the data (and bands), as the R plot
    # does, to remove dead headroom.
    if has_band:
        _, band_upper = _wilson(df["n"].to_numpy(), df["reference_n"].to_numpy())
        top = max(float(df["comparison_percentage"].max()), float(band_upper.max()))
    else:
        top = float(df["comparison_percentage"].max())
    ymax = min(100, math.ceil(top / 5) * 5)
    ax.set_ylim(0, ymax)

    # Spread the right-edge labels vertically so lines that converge near the
    # final year do not have overlapping labels.
    if label_points:
        adjusted = _spread_positions([p[1] for p in label_points], ymax * 0.05)
        overflow = max(adjusted) - ymax
        if overflow > 0:
            adjusted = [y - overflow for y in adjusted]
        for (x, _y, topic, colour), y_label in zip(label_points, adjusted):
            ax.annotate(topic, (x, y_label), xytext=(4, 0), textcoords="offset points",
                        va="center", fontsize=8, color=colour, annotation_clip=False)
    ax.set_xlabel("Year")
    ax.set_ylabel("Share of reference records (%)")
    ax.set_title("Topic share within a reference literature")
    _clean_axes(ax)
    return ax
