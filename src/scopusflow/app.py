"""A local-first NiceGUI app over scopusflow-py.

The app runs on the user's own machine, so the Scopus key never leaves it and
requests originate from the user's own network.
The long harvest runs off the event loop, its per-cell progress streams into a
live terminal, and a panel mirrors every choice as runnable Python. A demo mode
replays the bundled corpus of real articles in place of a harvest, so the whole
flow works with no key and no pybliometrics.

Launch with ``scopusflow-gui`` (the console script) or ``scopusflow.app.launch()``.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import os
import queue
import shutil
import tempfile
import time

import pandas as pd

from .app_helpers import app_code_mirror, app_parse_progress

logger = logging.getLogger("scopusflow")

_FIELD_CHOICES = {
    "TITLE-ABS-KEY": "Title, abstract, keywords",
    "TITLE": "Title",
    "ABS": "Abstract",
    "AUTHKEY": "Keywords",
    "AUTH": "Author",
    "AFFIL": "Affiliation",
    "SRCTITLE": "Source title",
    "ALL": "All fields",
}


class _QueueHandler(logging.Handler):
    """A logging handler that enqueues formatted records for the UI to drain on
    the event loop (pushing to a NiceGUI element from a worker thread is unsafe)."""

    def __init__(self, q: queue.Queue):
        super().__init__()
        self._q = q

    def emit(self, record):
        try:
            self._q.put_nowait(self.format(record))
        except Exception:
            pass


def _demo_year_span() -> tuple[int, int]:
    """First and last year the bundled example harvest covers."""
    from .data import example_records

    years = example_records()["year"]
    return int(years.min()), int(years.max())


def _demo_rows(year: int, n: int | None = None) -> list[dict]:
    """Records for ``year``, taken from the bundled example harvest.

    The rows are real published articles rather than invented ones, so demo mode
    shows a visitor what a retrieval actually looks like. ``n`` caps how many a
    cell returns; left at ``None`` the whole year comes back, which is what the
    demo harvest asks for, since the bundled set is a complete pull and its rows
    per year are then the real publications per year. Two edges need a rule,
    because the corpus covers one decade only and holds an uneven number of
    records in each of its years:

    * A year outside that span yields nothing, since padding it with repeats of
      a neighbouring year would double records up and bend the trend figure out
      of shape. The caller reports the empty cell.
    * A year holding fewer than ``n`` records yields only what it holds, so the
      demo table is short rather than padded out.
    """
    from .data import example_records

    frame = example_records()
    rows = frame[frame["year"] == int(year)]
    return (rows if n is None else rows.head(n)).to_dict("records")


def _demo_worker(plan, should_stop):
    """Replay a harvest: log per-cell progress and return real records from the
    bundled example corpus, over the stable schema, so the full UX works offline.

    Whatever terms were typed, the records returned are the bundled ones, since
    demo mode never contacts the API. A cell for a year the corpus does not
    cover comes back empty, and says so in the log.
    """
    import scopusflow as sf

    first, last = _demo_year_span()
    cells = plan.cells()
    total = len(cells)
    rows: list[dict] = []
    for cell in cells:
        if should_stop():
            logger.info("Stopped before cell %d/%d.", cell.cell, total)
            break
        logger.info("Cell %d/%d: fetching %s", cell.cell, total, cell.query)
        time.sleep(0.7)
        year = int(cell.year) if cell.year is not None else last
        found = _demo_rows(year)
        if not found:
            logger.info(
                "  %d is outside the bundled example harvest (%d-%d); no records.",
                year, first, last,
            )
        rows.extend(found)
    df = pd.DataFrame(rows, columns=sf.RECORD_COLUMNS)
    if len(df):
        df["entry_number"] = range(1, len(df) + 1)
    logger.info("Retrieved %d records.", len(df))
    return df


def _demo_comparison(reference, terms, years):
    """Synthesise a topic comparison so the compare flow works offline.

    Unlike the demo harvest, which replays real records, the numbers here are
    invented. A comparison is a set of per-year counts that only the Scopus
    count endpoint can answer, and the bundled corpus is one query's records
    rather than counts for arbitrary terms, so this simulates the shape of an
    API response rather than reporting measured data.
    """
    from .compare import _assemble

    ys = sorted(int(y) for y in years)
    span = max(len(ys) - 1, 1)
    ref_counts = {y: 1000 + (y - ys[0]) * 120 for y in ys}
    comparison = []
    for i, term in enumerate(terms):
        base = 0.06 + 0.07 * i
        growth = 0.03 * (i + 1)
        counts = {
            y: int(ref_counts[y] * (base + growth * (y - ys[0]) / span)) for y in ys
        }
        comparison.append((term, f"{reference} AND {term}", counts))
    return _assemble(reference, reference, ref_counts, comparison, ys)


def _demo_compare_worker(reference, terms, years):
    """Stream per-term progress, then synthesise a comparison, so the compare
    flow shows live progress offline (mirrors _demo_worker). The log lines use
    the "Cell k/N:" form the progress parser understands."""
    total = len(terms) + 1
    ny = len({int(y) for y in years})
    logger.info("Cell 1/%d: counting reference across %d year(s)", total, ny)
    time.sleep(0.5)
    for i, term in enumerate(terms):
        logger.info("Cell %d/%d: counting '%s'", i + 2, total, term)
        time.sleep(0.5)
    return _demo_comparison(reference, terms, years)


def _init_key(key: str) -> None:
    """Configure pybliometrics with the user's key for this session."""
    import pybliometrics

    pybliometrics.init(keys=[key])


def launch(host: str = "127.0.0.1", port: int = 8080, show: bool = True,
           reload: bool = False) -> None:
    """Start the app. Binds to 127.0.0.1 so it is reachable only from this
    machine and the key is never exposed on the network."""
    from nicegui import run, ui

    import scopusflow as sf

    this_year = datetime.date.today().year
    demo_first, demo_last = _demo_year_span()

    @ui.page("/")
    def index():  # a fresh page scope per client
        # Per-session UI state. The active pybliometrics key is process-global
        # (set by _init_key), so this local app assumes one active session.
        job = {"running": False, "stop": False, "records": None, "timer": None}
        # Harvest checkpoints live under the temp directory (not the working
        # directory) so search terms do not linger on disk, and the tree is
        # removed when the tab closes, mirroring the R app's session cleanup.
        cache_base = os.path.join(tempfile.gettempdir(), "scopusflow-app")
        log_queue: queue.Queue = queue.Queue()
        handler = _QueueHandler(log_queue)
        handler.setFormatter(logging.Formatter("%(message)s"))
        # A separate pump for the comparison, so its per-term progress feeds the
        # compare card without entangling with the harvest's terminal.
        cmp_log_queue: queue.Queue = queue.Queue()
        cmp_handler = _QueueHandler(cmp_log_queue)
        cmp_handler.setFormatter(logging.Formatter("%(message)s"))

        # When the user closes the tab, stop a running harvest (so a real fetch
        # does not keep spending quota) and tear down the log pump at once.
        def _on_disconnect():
            job["stop"] = True
            if job["timer"] is not None:
                try:
                    job["timer"].cancel()
                except Exception:
                    pass
            scopus_logger = logging.getLogger("scopusflow")
            scopus_logger.removeHandler(handler)
            scopus_logger.removeHandler(cmp_handler)
            shutil.rmtree(cache_base, ignore_errors=True)

        ui.context.client.on_disconnect(_on_disconnect)

        ui.markdown("## scopusflow")
        ui.markdown(
            "Scopus searches without writing code. The app runs on your own "
            "machine, so your API key stays local and requests come from your own "
            "network. Enter a key, or switch on Demo mode to try the whole "
            "workflow with no key, on a bundled set of real published articles."
        ).classes("text-sm text-grey-7")

        with ui.row().classes("w-full no-wrap"):
            with ui.column().classes("w-1/2"):
                with ui.card().classes("w-full"):
                    key_in = ui.input("Scopus API key", password=True,
                                      placeholder="paste your key (stays on this machine)")
                    demo = ui.switch("Demo mode (no key needed)", value=True)
                    query_in = ui.input("Search terms", value="graphene supercapacitor") \
                        .classes("w-full")
                    field_in = ui.select(_FIELD_CHOICES, value="TITLE-ABS-KEY",
                                         label="Search in").classes("w-full")
                    use_years = ui.switch("Partition by year (recommended)", value=True)
                    ui.label("Years").classes("text-sm text-grey-7")
                    # Opens on the span the bundled example harvest covers, so
                    # demo mode (on by default) has records for every cell. The
                    # slider still reaches the current year for a live search.
                    years_in = ui.range(min=1960, max=this_year,
                                        value={"min": demo_first, "max": demo_last}) \
                        .props('label-always aria-label="Years"')
                    ui.label("Detail").classes("text-sm text-grey-7")
                    view_in = ui.radio(["STANDARD", "COMPLETE"], value="STANDARD") \
                        .props('inline aria-label="Detail level"')
                    with ui.row():
                        ui.button("Check plan", on_click=lambda: on_count()).props("outline")
                        fetch_btn = ui.button("Fetch records", on_click=lambda: on_fetch()) \
                            .props("color=primary")
                        ui.button("Cancel", on_click=lambda: on_cancel()).props(
                            "outline color=negative"
                        )
            with ui.column().classes("w-1/2"):
                with ui.card().classes("w-full"):
                    ui.label("Reproducible Python").classes("text-subtitle2")
                    code = ui.code("", language="python").classes("w-full")
                    ui.button(
                        "Download script (.py)",
                        on_click=lambda: ui.download.content(_code_text(), "scopusflow.py"),
                    ).props("outline size=sm")

        size_label = ui.label("").classes("text-grey-8")
        progress = ui.linear_progress(value=0, show_value=False).props("instant-feedback")
        progress_label = ui.label("").classes("text-sm text-grey-7")
        with ui.expansion("Live terminal", icon="terminal").classes("w-full"):
            log = ui.log(max_lines=1000).classes("w-full h-64") \
                .style("background:#0E2233; color:#E8F1F2; font-family:monospace; font-size:12px")
        results = ui.column().classes("w-full")

        with ui.card().classes("w-full"):
            ui.label("Compare topics").classes("text-subtitle2")
            ui.label(
                "How sub-topics co-occur with your search over time, as a share "
                "of it. Your search terms are the reference topic."
            ).classes("text-sm text-grey-7")
            cmp_terms = ui.input(
                "Comparison terms (comma-separated)",
                value="machine learning, deep learning",
            ).classes("w-full")
            with ui.row().classes("items-center gap-4"):
                cmp_highlight = ui.select({"": "(none)"}, value="",
                                          label="Highlight topic").classes("w-48")
                cmp_band = ui.switch("Stability band", value=True)
                cmp_counts = ui.switch("Counts in label", value=True)
            cmp_note = ui.label("").classes("text-sm text-grey-7")
            ui.button("Compare topics", on_click=lambda: on_compare()) \
                .props("outline color=primary")
            cmp_progress = ui.linear_progress(value=0, show_value=False) \
                .props("instant-feedback")
            cmp_progress.visible = False
            cmp_progress_label = ui.label("").classes("text-sm text-grey-7")
            compare_results = ui.column().classes("w-full")

        def _years():
            if not use_years.value:
                return None
            v = years_in.value or {}
            return list(range(int(v.get("min", this_year)), int(v.get("max", this_year)) + 1))

        def _cmp_terms_list():
            # Drop blanks and duplicates (order preserved) so a repeated term does
            # not spend a redundant count request or double a legend entry.
            terms = [t.strip() for t in (cmp_terms.value or "").split(",") if t.strip()]
            return list(dict.fromkeys(terms))

        def _code_text():
            return app_code_mirror(
                query=query_in.value, years=_years(),
                field=field_in.value or None, view=view_in.value,
                partition="year" if use_years.value else "none",
                compare_terms=_cmp_terms_list(),
                highlight=cmp_highlight.value or None,
                interval=cmp_band.value, counts_in_legend=cmp_counts.value,
            )

        def update_code():
            code.content = _code_text()

        def update_compare_meta():
            # Keep the highlight choices in step with the entered terms, and show
            # the comparison's count-request cost (one request per term per year,
            # plus one per year for the reference topic itself).
            terms = _cmp_terms_list()
            opts = {"": "(none)"}
            for t in terms:
                opts[t] = t
            value = cmp_highlight.value if cmp_highlight.value in opts else ""
            cmp_highlight.set_options(opts, value=value)
            if terms and not demo.value:
                yrs = _years() or list(range(this_year - 5, this_year + 1))
                n = (len(terms) + 1) * len(yrs)
                warn = (
                    " Consider fewer terms or years if that is more than you need."
                    if n > 80 else ""
                )
                cmp_note.text = (f"({len(terms)} term(s) + the reference) x "
                                 f"{len(yrs)} year(s) = {n} count requests.{warn}")
            else:
                cmp_note.text = ""

        for el in (query_in, field_in, use_years, years_in, view_in):
            el.on_value_change(update_code)
        for el in (cmp_highlight, cmp_band, cmp_counts):
            el.on_value_change(update_code)
        cmp_terms.on_value_change(lambda: (update_code(), update_compare_meta()))
        for el in (use_years, years_in, demo):
            el.on_value_change(update_compare_meta)
        update_code()
        update_compare_meta()

        async def on_count():
            if job["running"]:
                ui.notify("Wait for the current retrieval to finish.", type="warning")
                return
            yrs = _years()
            cells = len(yrs) if yrs else 1
            unit = "cell" if cells == 1 else "year-cells"
            span = f", {yrs[0]}–{yrs[-1]}" if yrs else ""
            if not (query_in.value or "").strip():
                ui.notify("Enter search terms first.", type="warning")
                return
            if demo.value:
                # Counted rather than estimated: the bundled corpus holds an
                # uneven number of records per year, and none at all outside its
                # own decade. An unpartitioned plan is one cell, which
                # _demo_worker serves from the corpus's last year.
                n = sum(len(_demo_rows(y)) for y in (yrs or [demo_last]))
                size_label.text = (
                    f"Demo plan: {cells} {unit}{span}; would replay {n} records "
                    f"from the bundled example harvest."
                )
                return
            if not (key_in.value or "").strip():
                ui.notify("Enter your Scopus API key, or switch on Demo mode.",
                          type="warning")
                return
            size_label.text = "Checking size…"
            try:
                _init_key((key_in.value or "").strip())
                n = await run.io_bound(
                    sf.scopus_count, query_in.value, yrs,
                    field_in.value or None, view_in.value
                )
                size_label.text = (
                    f"This query matches {n:,} records across {cells} {unit}{span}."
                )
            except Exception as exc:
                size_label.text = ""
                ui.notify(f"Could not size the search: {exc}", type="negative")

        def _drain():
            while True:
                try:
                    line = log_queue.get_nowait()
                except queue.Empty:
                    break
                log.push(line)
                prog = app_parse_progress([line])
                if prog:
                    progress.set_value(max(prog["done"] - 1, 0) / max(prog["total"], 1))
                    progress_label.text = f"Fetching cell {prog['done']} of {prog['total']}"

        def _cmp_drain():
            while True:
                try:
                    line = cmp_log_queue.get_nowait()
                except queue.Empty:
                    break
                log.push(line)  # the live terminal also shows comparison progress
                prog = app_parse_progress([line])
                if prog:
                    cmp_progress.set_value(prog["done"] / max(prog["total"], 1))
                    cmp_progress_label.text = line

        def _render(records):
            results.clear()
            with results:
                if records is None or len(records) == 0:
                    ui.label("No records.")
                    return
                ui.label(f"{len(records):,} records").classes("text-h6")
                cols = [c for c in ["title", "year", "publication", "citations"]
                        if c in records.columns]
                columns = [
                    {"name": c, "label": c.title(), "field": c,
                     "align": "right" if c in ("year", "citations") else "left"}
                    for c in cols
                ]
                ui.table(columns=columns, rows=records[cols].to_dict("records"),
                         pagination=8).props("dense").classes("w-full")
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                with ui.row().classes("w-full no-wrap"):
                    with ui.pyplot(figsize=(6, 3.2)):
                        sf.plot_trend(sf.year_counts(records), ax=plt.gca())
                        plt.tight_layout()
                    with ui.pyplot(figsize=(6, 3.2)):
                        sf.plot_top(sf.top(records, by="source"), ax=plt.gca())
                        plt.tight_layout()
                with ui.row():
                    ui.button(
                        "Records (.csv)",
                        on_click=lambda: ui.download.content(
                            records.to_csv(index=False), "scopus-records.csv"),
                    ).props("outline size=sm")
                    ui.button(
                        "BibTeX (.bib)",
                        on_click=lambda: ui.download.content(
                            sf.to_bibtex(records), "scopus-records.bib"),
                    ).props("outline size=sm")
                    ui.button(
                        "RIS (.ris)",
                        on_click=lambda: ui.download.content(
                            sf.to_ris(records), "scopus-records.ris"),
                    ).props("outline size=sm")

        async def on_fetch():
            if job["running"]:
                ui.notify("A retrieval is already running.", type="warning")
                return
            if not (query_in.value or "").strip():
                ui.notify("Enter search terms first.", type="warning")
                return
            if not demo.value and not (key_in.value or "").strip():
                ui.notify("Enter your Scopus API key, or switch on Demo mode.",
                          type="warning")
                return
            job["running"], job["stop"], job["records"] = True, False, None
            log.clear()
            results.clear()
            size_label.text = ""
            progress.set_value(0)
            progress_label.text = "Working…"
            fetch_btn.disable()
            scopus_logger = logging.getLogger("scopusflow")
            scopus_logger.setLevel(logging.INFO)
            timer = None
            try:
                # Attach the log pump inside the try so the finally always tears
                # it down, even if timer creation or planning fails.
                scopus_logger.addHandler(handler)
                timer = ui.timer(0.2, _drain)
                job["timer"] = timer
                plan = sf.SearchPlan(
                    query_in.value, years=_years(),
                    field=field_in.value or None, view=view_in.value,
                    partition="year" if use_years.value else "none",
                )
                if demo.value:
                    records = await run.io_bound(_demo_worker, plan, lambda: job["stop"])
                else:
                    _init_key((key_in.value or "").strip())
                    # A stable key over the whole plan (not just the query) so a
                    # resumed run reuses its checkpoints and two plans that differ
                    # only by year do not collide.
                    digest = hashlib.sha1(
                        repr((query_in.value, _years(), field_in.value, view_in.value))
                        .encode("utf-8")).hexdigest()[:16]
                    cache = os.path.join(cache_base, digest)
                    records = await run.io_bound(
                        sf.fetch_plan, plan, cache, True, "parquet", lambda: job["stop"]
                    )
                job["records"] = records
                _render(records)
                progress.set_value(1.0)
                n = len(records)
                ui.notify(f"Retrieved {n:,} records.",
                          type="positive" if n else "warning")
            except Exception as exc:  # surface any failure into the UI, not a crash
                logger.info("Error: %s", exc)
                progress.set_value(0)
                ui.notify(f"Retrieval did not complete: {exc}", type="negative")
            finally:
                if timer is not None:
                    timer.cancel()
                _drain()
                scopus_logger.removeHandler(handler)
                job["timer"] = None
                job["running"] = False
                progress_label.text = ""
                fetch_btn.enable()

        def on_cancel():
            if job["running"]:
                job["stop"] = True
                ui.notify("Stopping after the current cell…", type="info")
            else:
                ui.notify("Nothing to cancel.", type="info")

        async def on_compare():
            terms = _cmp_terms_list()
            if not (query_in.value or "").strip():
                ui.notify("Enter search terms first (used as the reference topic).",
                          type="warning")
                return
            if not terms:
                ui.notify("Enter at least one comparison term.", type="warning")
                return
            if job["running"]:
                ui.notify("Wait for the current retrieval to finish.", type="warning")
                return
            if not demo.value and not (key_in.value or "").strip():
                ui.notify("Enter your Scopus API key, or switch on Demo mode.",
                          type="warning")
                return
            yrs = _years() or list(range(this_year - 5, this_year + 1))
            compare_results.clear()
            scopus_logger = logging.getLogger("scopusflow")
            scopus_logger.setLevel(logging.INFO)
            cmp_progress.set_value(0)
            cmp_progress.visible = True
            cmp_progress_label.text = "Comparing topics…"
            timer = None
            try:
                # Stream each count step's progress into the compare card (and the
                # live terminal) via the dedicated pump.
                scopus_logger.addHandler(cmp_handler)
                timer = ui.timer(0.2, _cmp_drain)
                if demo.value:
                    cmp = await run.io_bound(_demo_compare_worker, query_in.value, terms, yrs)
                else:
                    _init_key((key_in.value or "").strip())
                    cmp = await run.io_bound(
                        sf.compare_topics, query_in.value, terms, yrs,
                        field_in.value or None, view_in.value,
                    )
                cmp_progress.set_value(1.0)
                with compare_results:
                    import matplotlib
                    matplotlib.use("Agg")
                    import matplotlib.pyplot as plt
                    # The highlight must name a topic with a plottable share, so
                    # mirror plot_comparison's own notna filter and a topic the plot
                    # drops cannot be forwarded as highlight (which would raise).
                    mask = ((cmp["query_type"] == "comparison")
                            & cmp["comparison_percentage"].notna())
                    result_topics = set(cmp.loc[mask, "abridged_query"])
                    hl = cmp_highlight.value or None
                    if hl not in result_topics:
                        hl = None
                    with ui.pyplot(figsize=(8, 4.4)):
                        sf.plot_comparison(
                            cmp, ax=plt.gca(), highlight=hl,
                            interval=cmp_band.value,
                            counts_in_legend=cmp_counts.value,
                        )
                        plt.tight_layout()
                        plt.gcf().canvas.draw()  # settle the label de-collision
                    if demo.value:
                        # The figure's own caption names the Search API, which is
                        # true of a real comparison but not of this one, so say
                        # plainly where the demo's numbers came from.
                        ui.label(
                            "Demo mode: these counts are illustrative rather "
                            "than retrieved. The figure shows the shape a real "
                            "comparison returns, not measured shares."
                        ).classes("text-sm text-grey-7")
                    ui.button(
                        "Comparison (.csv)",
                        on_click=lambda: ui.download.content(
                            cmp.to_csv(index=False), "scopus-comparison.csv"),
                    ).props("outline size=sm")
            except Exception as exc:
                compare_results.clear()
                ui.notify(f"Comparison failed: {exc}", type="negative")
            finally:
                if timer is not None:
                    timer.cancel()
                _cmp_drain()
                scopus_logger.removeHandler(cmp_handler)
                cmp_progress.visible = False
                cmp_progress_label.text = ""

    ui.run(host=host, port=port, show=show, reload=reload, title="scopusflow")


if __name__ in {"__main__", "__mp_main__"}:
    launch()
