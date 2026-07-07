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


def _decollide_once(ax, anns, xs, y_true, ymax, min_gap, fontsize=8):
    """Spread end-of-line labels vertically so none overlaps another, returning
    whether any label moved.

    The minimum separation is one line of label text converted to data units in
    the current layout, so the de-collision holds at the figure's actual size
    rather than relying on a fixed fraction of the axis range. The line height is
    derived from the font size and dpi rather than each label's window extent,
    because an annotation's extent also covers its leader line. It is meant to run
    from a draw (see the handler in :func:`plot_comparison`). Mirrors the R plot's
    vertical label de-collision."""
    try:
        fig = ax.figure
        line_px = fontsize * fig.dpi / 72 * 1.25  # one line of text, with spacing
        inv = ax.transData.inverted()
        line_data = abs(inv.transform((0, line_px))[1] - inv.transform((0, 0))[1])
    except Exception:
        return False
    gap = max(min_gap, line_data)
    adjusted = _spread_positions(y_true, gap)
    overflow = max(adjusted) - ymax
    if overflow > 0:
        adjusted = [y - overflow for y in adjusted]
    moved = False
    for ann, x, y in zip(anns, xs, adjusted):
        if abs(ann.xyann[1] - y) > 1e-3:
            ann.xyann = (x, y)
            moved = True
    return moved


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

    # Place each label at its line's endpoint, with a thin leader. The labels are
    # spread apart at the end (see _decollide_labels), once the final layout is
    # known, so none overlaps another.
    anns, label_xs, label_y_true = [], [], []
    if to_label:
        years = df["year"]
        dx = (float(years.max()) - float(years.min())) * 0.015 + 0.1
        for x, y_true, topic, colour, _is_hi in to_label:
            anns.append(ax.annotate(
                topic, xy=(x, y_true), xytext=(x + dx, y_true), textcoords="data",
                va="center", ha="left", fontsize=8, color=colour,
                annotation_clip=False,
                # Semi-transparent leader so one that passes behind another
                # topic's label does not compete with the text; the label text
                # itself stays fully opaque.
                arrowprops=dict(arrowstyle="-", color=colour, lw=0.6, alpha=0.4,
                                shrinkA=1, shrinkB=3),
            ))
            label_xs.append(x + dx)
            label_y_true.append(y_true)
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

    if anns:
        # Re-spread the labels on every draw, measuring the rendered text height in
        # the layout that actually applies, so they never overlap however the lines
        # converge or the figure is sized. Running on the draw means it stays
        # correct after the caller tightens the layout. A guard stops the redraw it
        # requests from recursing once the positions have settled.
        _busy = {"on": False}

        def _on_draw(_event=None):
            if _busy["on"]:
                return
            _busy["on"] = True
            try:
                if _decollide_once(ax, anns, label_xs, label_y_true, ymax, gap):
                    ax.figure.canvas.draw_idle()
            finally:
                _busy["on"] = False

        ax.figure.canvas.mpl_connect("draw_event", _on_draw)
        # An initial draw so a one-shot render (savefig without a prior draw) still
        # gets de-collided labels.
        try:
            ax.figure.canvas.draw()
        except Exception:
            pass
    return ax
