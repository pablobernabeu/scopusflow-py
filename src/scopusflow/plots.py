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
                    counts_in_legend: bool = True, ax=None):
    """Plot each comparison topic's share of the reference literature over time.

    ``comparison`` is the frame from :func:`scopusflow.compare.compare_topics`.
    With ``interval`` a shaded Wilson band shows how stable each yearly share is
    (illustrative, not a confidence interval — Scopus counts are exact).
    ``highlight`` names one topic to draw in an accent colour, the rest in grey.
    With ``counts_in_legend`` (the default) each label carries the topic's total
    record count, for example ``machine learning (n = 1,204)``. Returns the
    matplotlib ``Axes``.
    """
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    required = {"query_type", "abridged_query", "year", "comparison_percentage"}
    if not required.issubset(comparison.columns):
        raise ValueError("comparison must be a topic-comparison frame.")

    comp_all = comparison[comparison["query_type"] == "comparison"]
    # A year whose reference has no records carries no defined share; it is
    # dropped and noted in the caption, mirroring the R plot.
    n_missing = int(comp_all["comparison_percentage"].isna().sum())
    df = comp_all[comp_all["comparison_percentage"].notna()].copy()
    if df.empty:
        raise ValueError("comparison has no comparison topics with a finite share to plot.")

    # The reference topic names the subtitle (it is the 100% denominator).
    ref_rows = comparison[comparison["query_type"] == "reference"]
    ref_names = ref_rows["abridged_query"].dropna().unique() if len(ref_rows) else []
    ref_label = str(ref_names[0]) if len(ref_names) == 1 else None

    order = (df.groupby("abridged_query")["average_comparison_percentage"].first()
             .reset_index()
             .sort_values(["average_comparison_percentage", "abridged_query"],
                          ascending=[False, True]))
    topics = list(order["abridged_query"])
    if highlight is not None and highlight not in topics:
        raise ValueError(f"highlight must be one of: {', '.join(topics)}.")

    # Optionally append each topic's total record count to its label.
    has_counts = counts_in_legend and "n" in df.columns
    totals = df.groupby("abridged_query")["n"].sum() if has_counts else None

    def _label(topic):
        return f"{topic} (n = {int(totals[topic]):,})" if has_counts else topic

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
        ax.plot(sub["year"], sub["comparison_percentage"], color=colour,
                linewidth=width, label=_label(topic))
        ax.scatter(sub["year"], sub["comparison_percentage"], color=colour, s=14, zorder=3)
        last = sub.iloc[-1]
        label_points.append((float(last["year"]), float(last["comparison_percentage"]),
                             _label(topic), colour, is_hi))

    # Cap the y-axis at the next 5% above the data (and bands), as the R plot
    # does, to remove dead headroom.
    if has_band:
        _, band_upper = _wilson(df["n"].to_numpy(), df["reference_n"].to_numpy())
        top = max(float(df["comparison_percentage"].max()), float(band_upper.max()))
    else:
        top = float(df["comparison_percentage"].max())
    ymax = min(100, math.ceil(top / 5) * 5)
    ax.set_ylim(0, ymax)

    # Label the lines directly when they fit legibly; otherwise fall back to a
    # legend. The gap is the minimum vertical separation between labels.
    gap = ymax * 0.055
    if highlight is not None:
        to_label = [p for p in label_points if p[4]]
    elif len(topics) <= 8 and (len(topics) - 1) * gap <= ymax:
        to_label = label_points
    else:
        to_label = []
        ax.legend(fontsize=8, loc="best", frameon=False,
                  ncol=2 if len(topics) > 8 else 1)

    if to_label:
        # Spread the labels apart, then draw a thin leader from each line's true
        # endpoint to its (possibly nudged) label so the link is unambiguous.
        adjusted = _spread_positions([p[1] for p in to_label], gap)
        overflow = max(adjusted) - ymax
        if overflow > 0:
            adjusted = [y - overflow for y in adjusted]
        years = df["year"]
        dx = (float(years.max()) - float(years.min())) * 0.015 + 0.1
        for (x, y_true, topic, colour, _is_hi), y_label in zip(to_label, adjusted):
            ax.annotate(
                topic, xy=(x, y_true), xytext=(x + dx, y_label), textcoords="data",
                va="center", ha="left", fontsize=8, color=colour,
                annotation_clip=False,
                arrowprops=dict(arrowstyle="-", color=colour, lw=0.6, shrinkA=1, shrinkB=3),
            )
    ax.set_xlabel("")
    ax.set_ylabel("Share of reference records")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=100, decimals=0))
    ax.set_title("Topic share within a reference literature, over time",
                 loc="left", fontsize=12, pad=22)
    if ref_label:
        ax.annotate(
            f"Each line: % of '{ref_label}' records that also match the topic",
            xy=(0, 1), xycoords="axes fraction", xytext=(0, 6),
            textcoords="offset points", ha="left", va="bottom",
            fontsize=9, color="#555555",
        )
    # A caption that names the source and guards against reading the illustrative
    # Wilson band as an inferential confidence interval (it is not).
    caption = (f"Source: 'Scopus' Search API. Years {int(df['year'].min())} "
               f"to {int(df['year'].max())}.")
    if has_band:
        caption += ("\nShaded band: illustrative Wilson stability range "
                    "(not a confidence interval), wider where the reference set is small.")
    if n_missing > 0:
        plural = "" if n_missing == 1 else "s"
        caption += (f"\n{n_missing} year-topic value{plural} omitted for want "
                    "of reference records.")
    ax.annotate(caption, xy=(0, 0), xycoords="axes fraction", xytext=(0, -24),
                textcoords="offset points", ha="left", va="top",
                fontsize=7.5, color="#737373")
    _clean_axes(ax)
    return ax
