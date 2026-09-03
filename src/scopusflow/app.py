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
import warnings

import pandas as pd

from .app_helpers import (
    app_busy_message,
    app_code_mirror,
    app_parse_progress,
    app_search_query,
    app_session_dir,
)

logger = logging.getLogger("scopusflow")

#: What the "Download script (.py)" button names the file. Never
#: "scopusflow.py": Python puts a script's own directory first on sys.path,
#: so a script saved under the package's name would import itself instead of
#: the package and fail where it landed. Matches the R twin's
#: scopusflow-script.R.
_SCRIPT_FILENAME = "scopusflow-script.py"

#: Where the package's own modules live, so a harvest's warnings can be told
#: apart from a dependency's.
_PACKAGE_DIR = os.path.dirname(__file__)

#: The Meridian brand tokens, as the family's stylesheets define them
#: (``docs/stylesheets/brand.css`` here, ``pkgdown/extra.scss`` in the R twin).
#: The primary is the deep teal the stylesheets reserve for links and buttons,
#: which carries white text at 6.0:1, rather than the lighter ``--brand-teal``
#: used for borders and edges, which does not.
_BRAND_PRIMARY = "#0F6E6E"
_BRAND_INK = "#0E2233"
_BRAND_AMBER = "#E8A33D"
#: The amber that reads on a light ground, for the one caption that warns.
_BRAND_AMBER_DARK = "#9C5A00"

#: The live terminal's foreground on the ink ground. Not a family token.
_TERMINAL_INK = "#E8F1F2"

#: The field tags offered in the "Search in" selector, each one
#: :data:`scopusflow.query.FIELD_TAGS` documents, so a tag read off the
#: generated script can be looked up. The empty key is the untagged case: it
#: sends the query exactly as typed, which is what a hand-written boolean
#: expression carrying its own tags needs, and it is what every
#: ``field_in.value or None`` in the app turns into ``field=None``. The R twin
#: offers the same tags under the same labels, "(none)" last.
_FIELD_CHOICES = {
    "TITLE-ABS-KEY": "Title, abstract, keywords",
    "TITLE": "Title",
    "ABS": "Abstract",
    "AUTHKEY": "Keywords",
    "AUTH": "Author",
    "AFFIL": "Affiliation",
    "SRCTITLE": "Source title",
    "ALL": "All fields",
    "": "(none)",
}


def _figure_props(label: str) -> str:
    """Props that give a figure an accessible name.

    A NiceGUI figure is a ``div`` holding the SVG matplotlib wrote, which has
    no title and no name of its own, so a screen reader reads its loose tick
    labels or nothing at all. ``role=img`` with a label names the whole panel
    and hides its innards. NiceGUI parses props out of this string, so a
    quotation mark in a label built from the user's own terms would break the
    parse: those and the backslashes are dropped.
    """
    clean = " ".join(label.replace('"', "").replace("\\", "").split())
    return f'role=img aria-label="{clean}"'


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

    The rows are real published articles, so demo mode
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
      demo table is short, and never padded out.
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


def _fetch_worker(plan, cache_dir, should_stop):
    """Run the harvest and return the records with the warnings it raised.

    ``fetch_plan`` reports a short cell, an unreadable checkpoint and a
    checkpoint written by another plan through :mod:`warnings`, which would land
    on the stderr of the process behind the browser tab and never reach the
    person driving the app. Each one is re-emitted on the "scopusflow" logger as
    it is raised, so it streams into the live terminal, and returned so the
    completion notice can say the harvest may be incomplete. The filters are
    forced to "always" for the duration, since the default hides every repeat of
    a warning already raised from the same line, which is exactly how a second
    short cell would be lost. Only warnings raised inside the package are taken,
    since "always" also un-hides the deprecation notices a dependency raises on
    the way past, and a complete harvest announced as possibly incomplete
    because pandas deprecated a keyword would say the opposite of the truth.
    """
    import scopusflow as sf

    caught: list[str] = []

    def show(message, category, filename, lineno, file=None, line=None):
        if not str(filename).startswith(_PACKAGE_DIR):
            return
        caught.append(str(message))
        logger.warning("%s", message)

    with warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.showwarning = show
        records = sf.fetch_plan(plan, cache_dir, True, "parquet", should_stop)
    return records, caught


def _search_record(records, demo: bool) -> str:
    """The PRISMA-S search record for the download button, as Markdown.

    In demo mode the rows are the bundled corpus, whose ``query`` column holds
    the search that produced the corpus rather than anything the user typed.
    Carried into the record it would state, in a paragraph written to be pasted
    into a manuscript, an expression nobody ran. The column is dropped instead,
    so the expression comes out unrecorded like the retrieval time beside it,
    and the file opens by saying where its rows came from.
    """
    import scopusflow as sf

    if not demo:
        return sf.scopus_search_report(records).format(style="markdown")
    replayed = records.copy()
    if "query" in replayed.columns:
        replayed["query"] = pd.NA
    note = ("> Demo mode: these records were replayed from the bundled example "
            "harvest rather than retrieved from Scopus, so the search below is "
            "not the one you entered.")
    return note + "\n\n" + sf.scopus_search_report(replayed).format(style="markdown")


def _demo_comparison(reference, terms, years):
    """Synthesise a topic comparison so the compare flow works offline.

    Unlike the demo harvest, which replays real records, the numbers here are
    invented. A comparison is a set of per-year counts that only the Scopus
    count endpoint can answer, and the bundled corpus holds one query's
    records, with no counts for arbitrary terms among them. What follows
    simulates the shape of an API response. Nothing in it is measured.
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
        # "busy" names the long job in flight ("fetch", "count", "compare")
        # or is None. Only one may run: they share the process-wide key and
        # the one "scopusflow" logger, whose records would otherwise reach
        # both log pumps at once.
        job = {"busy": None, "stop": False, "records": None, "timer": None}
        # Harvest checkpoints live under the temp directory (not the working
        # directory) so search terms do not linger on disk. The base is shared
        # by every open tab, so each page scope keys its checkpoints under its
        # own per-session subdirectory and, when the tab closes, removes only
        # that: removing the base would delete another session's checkpoints
        # mid-harvest.
        session_dir = app_session_dir(
            os.path.join(tempfile.gettempdir(), "scopusflow-app")
        )
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
            shutil.rmtree(session_dir, ignore_errors=True)

        ui.context.client.on_disconnect(_on_disconnect)

        # The app's own palette, so the buttons, the focus rings and the
        # progress bars are the family's rather than Quasar's stock blue, which
        # is also the only colour here that white text fails to clear.
        ui.colors(primary=_BRAND_PRIMARY, secondary=_BRAND_INK, accent=_BRAND_AMBER)

        # The page's own h1, as the R twin's page title renders: the app had
        # no top-level heading at all.
        ui.markdown("# scopusflow")
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
                    # What the app will do with the next click, said before the
                    # click rather than in a warning after it, as the R twin's
                    # key status line already does.
                    key_status = ui.label("").classes("text-sm")
                    query_in = ui.input("Search terms", value="graphene supercapacitor") \
                        .classes("w-full")
                    field_in = ui.select(_FIELD_CHOICES, value="TITLE-ABS-KEY",
                                         label="Search in").classes("w-full")
                    use_years = ui.switch("Partition by year (recommended)", value=True)
                    years_label = ui.label("Years").classes("text-sm text-grey-7")
                    # Opens on the span the bundled example harvest covers, so
                    # demo mode (on by default) has records for every cell. The
                    # slider still reaches the current year for a live search.
                    years_in = ui.range(min=1960, max=this_year,
                                        value={"min": demo_first, "max": demo_last}) \
                        .props('label-always aria-label="Years"')
                    # With partitioning off the range reaches neither the plan
                    # nor the comparison (which falls back to its own six-year
                    # span), so it goes with the toggle rather than standing
                    # there showing a span nothing is using. The R twin's
                    # conditionalPanel hides the same slider.
                    for el in (years_label, years_in):
                        el.bind_visibility_from(use_years, "value")
                    ui.label("Detail").classes("text-sm text-grey-7")
                    view_in = ui.radio(["STANDARD", "COMPLETE"], value="STANDARD") \
                        .props('inline aria-label="Detail level"')
                    # The most expensive control on the card, under the barest
                    # label: quota is charged by the request, so the smaller
                    # page COMPLETE returns is what the choice really costs.
                    ui.label(
                        "STANDARD returns 200 records a request; COMPLETE adds author "
                        "keywords but returns 25, so the same harvest costs about eight "
                        "times the requests."
                    ).classes("text-sm text-grey-7")
                    with ui.row():
                        ui.button("Check plan", on_click=lambda: on_count()).props("outline")
                        fetch_btn = ui.button("Fetch records", on_click=lambda: on_fetch()) \
                            .props("color=primary")
                        ui.button("Cancel", on_click=lambda: on_cancel()).props(
                            "outline color=negative"
                        )
            with ui.column().classes("w-1/2"):
                with ui.card().classes("w-full"):
                    # A heading in the page's outline (under the h1 the title
                    # renders as), kept at the card's own type size: the two
                    # section titles were the only structure to navigate by and
                    # neither was a heading at all.
                    ui.label("Reproducible Python").classes("text-subtitle2") \
                        .props("role=heading aria-level=2")
                    code = ui.code("", language="python").classes("w-full")
                    ui.button(
                        "Download script (.py)",
                        on_click=lambda: ui.download.content(_code_text(), _SCRIPT_FILENAME),
                    ).props("outline size=sm")

        size_label = ui.label("").classes("text-grey-8")
        progress = ui.linear_progress(value=0, show_value=False).props("instant-feedback")
        # Shown once a harvest starts, like the comparison's own bar just below:
        # a bar sitting at zero before anything has run reads as a stalled job.
        progress.visible = False
        progress_label = ui.label("").classes("text-sm text-grey-7")
        with ui.expansion("Live terminal", icon="terminal").classes("w-full"):
            log = ui.log(max_lines=1000).classes("w-full h-64") \
                .style(f"background:{_BRAND_INK}; color:{_TERMINAL_INK}; "
                       "font-family:monospace; font-size:12px")
        results = ui.column().classes("w-full")
        with results:
            ui.label("Fetch records to see them here.").classes("text-sm text-grey-7")

        with ui.card().classes("w-full"):
            ui.label("Compare topics").classes("text-subtitle2") \
                .props("role=heading aria-level=2")
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
            cmp_btn = ui.button("Compare topics", on_click=lambda: on_compare()) \
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

        def _query():
            # One trimmed query behind the harvest, the plan check, the
            # comparison and the checkpoint key; see app_search_query.
            return app_search_query(query_in.value)

        def _cmp_terms_list():
            # Drop blanks and duplicates (order preserved) so a repeated term does
            # not spend a redundant count request or double a legend entry.
            terms = [t.strip() for t in (cmp_terms.value or "").split(",") if t.strip()]
            return list(dict.fromkeys(terms))

        def _cmp_years():
            # A comparison needs an explicit span, so with "Partition by year"
            # off it falls back to the last six years. The cost note, the
            # mirrored script and the comparison itself all read the span here,
            # so the script always names the span that ran.
            return _years() or list(range(this_year - 5, this_year + 1))

        def _code_text():
            return app_code_mirror(
                query=query_in.value, years=_years(),
                field=field_in.value or None, view=view_in.value,
                partition="year" if use_years.value else "none",
                compare_terms=_cmp_terms_list(),
                compare_years=_cmp_years(),
                highlight=cmp_highlight.value or None,
                interval=cmp_band.value, counts_in_legend=cmp_counts.value,
                demo=demo.value,
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
                yrs = _cmp_years()
                n = (len(terms) + 1) * len(yrs)
                warn = (
                    " Consider fewer terms or years if that is more than you need."
                    if n > 80 else ""
                )
                cmp_note.text = (f"({len(terms)} term(s) + the reference) x "
                                 f"{len(yrs)} year(s) = {n} count requests.{warn}")
            else:
                cmp_note.text = ""

        def update_key_status():
            # What the next click will do, in the three states the R twin's own
            # status line names, so a missing key is read before a button is
            # pressed rather than in the warning that follows it.
            if demo.value:
                key_status.text = ("Demo mode: real bundled records, simulated "
                                   "comparison, no key needed.")
                key_status.style(f"color:{_BRAND_PRIMARY}")
            elif (key_in.value or "").strip():
                key_status.text = "Key set."
                key_status.style(f"color:{_BRAND_PRIMARY}")
            else:
                key_status.text = "Enter your key to fetch."
                key_status.style(f"color:{_BRAND_AMBER_DARK}")

        def on_plan_change():
            # A size note answers for one plan, so any change to the plan drops
            # it. Left standing, it went on stating how much a search nobody had
            # asked about would retrieve.
            update_code()
            size_label.text = ""

        # demo is here too: the script says whether what the user saw was
        # replayed or retrieved, so toggling it must redraw the panel.
        for el in (query_in, field_in, use_years, years_in, view_in, demo):
            el.on_value_change(on_plan_change)
        for el in (cmp_highlight, cmp_band, cmp_counts):
            el.on_value_change(update_code)
        cmp_terms.on_value_change(lambda: (update_code(), update_compare_meta()))
        for el in (use_years, years_in, demo):
            el.on_value_change(update_compare_meta)
        for el in (key_in, demo):
            el.on_value_change(update_key_status)
        update_code()
        update_compare_meta()
        update_key_status()

        async def on_count():
            busy = app_busy_message(job["busy"])
            if busy:
                ui.notify(busy, type="warning")
                return
            yrs = _years()
            cells = len(yrs) if yrs else 1
            unit = "cell" if cells == 1 else "year-cells"
            span = f", {yrs[0]}–{yrs[-1]}" if yrs else ""
            if not _query():
                ui.notify("Enter search terms first.", type="warning")
                return
            if demo.value:
                # Counted, never estimated: the bundled corpus holds an
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
            job["busy"] = "count"
            try:
                _init_key((key_in.value or "").strip())
                n = await run.io_bound(
                    sf.scopus_count, _query(), yrs,
                    field_in.value or None, view_in.value
                )
                size_label.text = (
                    f"This query matches {n:,} records across {cells} {unit}{span}."
                )
            except Exception as exc:
                size_label.text = ""
                ui.notify(f"Could not size the search: {exc}", type="negative")
            finally:
                job["busy"] = None

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
            # The mode the records on screen came from, captured here rather
            # than read at click time: flipping Demo mode off does not clear
            # the results, so the search record has to keep telling the truth
            # about rows already drawn.
            was_demo = bool(demo.value)
            results.clear()
            with results:
                if records is None or len(records) == 0:
                    ui.label("No records.")
                    return
                ui.label(f"{len(records):,} records").classes("text-h6")
                if was_demo:
                    # The same honesty the demo comparison figure already
                    # carries: these rows are real published articles, but they
                    # were replayed from the bundled corpus, not retrieved.
                    ui.label(
                        "Demo mode: these records were replayed from the bundled "
                        "example harvest rather than retrieved from Scopus."
                    ).classes("text-sm text-grey-7")
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

                def _panel(draw, note, label):
                    # A panel that cannot be drawn is a short note in its place,
                    # never a failure that takes the record table and the export
                    # buttons with it.
                    panel = ui.pyplot(figsize=(6, 3.2)).props(_figure_props(label))
                    try:
                        with panel:
                            draw()
                            plt.tight_layout()
                    except Exception as exc:
                        panel.delete()
                        ui.label(f"{note} ({exc})").classes("text-sm text-grey-7")

                # Wrapping, since the three figures are wider together than a
                # narrow window.
                with ui.row().classes("w-full"):
                    # A record set whose cover dates are all missing has no
                    # years to plot, and one whose source titles or author names
                    # are all missing tallies to nothing, so no figure here can
                    # always be drawn.
                    _panel(lambda: sf.plot_trend(sf.year_counts(records), ax=plt.gca()),
                           "No trend to plot", "Records retrieved per year")
                    _panel(lambda: sf.plot_top(sf.top(records, by="source"), ax=plt.gca()),
                           "No source titles to tally",
                           "The most frequent sources, by records retrieved")
                    _panel(lambda: sf.plot_top(sf.top(records, by="author"), ax=plt.gca()),
                           "No author names to tally",
                           "The most frequent authors, by records retrieved")
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
                    # One de-duplicated DOI per row, under a doi header, which
                    # is the file the R twin's DOIs button writes and what a
                    # later diff_dois or an upload to another service reads.
                    ui.button(
                        "DOIs (.csv)",
                        on_click=lambda: ui.download.content(
                            pd.DataFrame({"doi": sf.extract_dois(records)})
                            .to_csv(index=False),
                            "scopus-dois.csv"),
                    ).props("outline size=sm")
                    # The PRISMA-S search record. In demo mode it carries no
                    # plan, no retrieval time and no expression, and says the
                    # rows were replayed rather than retrieved.
                    ui.button(
                        "Search record (.md)",
                        on_click=lambda: ui.download.content(
                            _search_record(records, was_demo),
                            "scopus-search-record.md"),
                    ).props("outline size=sm")

        async def on_fetch():
            busy = app_busy_message(job["busy"])
            if busy:
                ui.notify(busy, type="warning")
                return
            if not _query():
                ui.notify("Enter search terms first.", type="warning")
                return
            if not demo.value and not (key_in.value or "").strip():
                ui.notify("Enter your Scopus API key, or switch on Demo mode.",
                          type="warning")
                return
            job["busy"], job["stop"], job["records"] = "fetch", False, None
            log.clear()
            results.clear()
            size_label.text = ""
            progress.set_value(0)
            progress.visible = True
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
                    _query(), years=_years(),
                    field=field_in.value or None, view=view_in.value,
                    partition="year" if use_years.value else "none",
                )
                warned: list[str] = []
                if demo.value:
                    records = await run.io_bound(_demo_worker, plan, lambda: job["stop"])
                else:
                    _init_key((key_in.value or "").strip())
                    # A stable key over the whole plan (not just the query) so a
                    # resumed run reuses its checkpoints and two plans that differ
                    # only by year do not collide.
                    digest = hashlib.sha1(
                        repr((_query(), _years(), field_in.value, view_in.value))
                        .encode("utf-8")).hexdigest()[:16]
                    cache = os.path.join(session_dir, digest)
                    records, warned = await run.io_bound(
                        _fetch_worker, plan, cache, lambda: job["stop"]
                    )
                job["records"] = records
                progress.set_value(1.0)
                try:
                    _render(records)
                except Exception as exc:
                    # Showing the records is not retrieving them: a display
                    # failure must not be reported as a harvest that did not
                    # complete, which would hide a set that was paid for.
                    logger.info("Error: %s", exc)
                    ui.notify(f"Retrieved the records, but could not show them: {exc}",
                              type="warning", multi_line=True, close_button=True)
                n = len(records)
                if warned:
                    # A harvest that fell short of what the API reports is not a
                    # success to announce in green, and its warning is the one
                    # thing a completeness record depends on.
                    ui.notify(f"Retrieved {n:,} records, but the harvest may be "
                              f"incomplete. {warned[0]}",
                              type="warning", multi_line=True, close_button=True)
                else:
                    ui.notify(f"Retrieved {n:,} records.",
                              type="positive" if n else "warning")
            except Exception as exc:  # report any failure in the UI, never crash
                logger.info("Error: %s", exc)
                progress.set_value(0)
                progress.visible = False
                ui.notify(f"Retrieval did not complete: {exc}", type="negative")
            finally:
                if timer is not None:
                    timer.cancel()
                _drain()
                scopus_logger.removeHandler(handler)
                job["timer"] = None
                job["busy"] = None
                progress_label.text = ""
                fetch_btn.enable()

        def on_cancel():
            if job["busy"] == "fetch":
                job["stop"] = True
                ui.notify("Stopping after the current cell…", type="info")
            else:
                ui.notify("Nothing to cancel.", type="info")

        async def on_compare():
            terms = _cmp_terms_list()
            if not _query():
                ui.notify("Enter search terms first (used as the reference topic).",
                          type="warning")
                return
            if not terms:
                ui.notify("Enter at least one comparison term.", type="warning")
                return
            busy = app_busy_message(job["busy"])
            if busy:
                ui.notify(busy, type="warning")
                return
            if not demo.value and not (key_in.value or "").strip():
                ui.notify("Enter your Scopus API key, or switch on Demo mode.",
                          type="warning")
                return
            yrs = _cmp_years()
            job["busy"] = "compare"
            cmp_btn.disable()
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
                    cmp = await run.io_bound(_demo_compare_worker, _query(), terms, yrs)
                else:
                    _init_key((key_in.value or "").strip())
                    cmp = await run.io_bound(
                        sf.compare_topics, _query(), terms, yrs,
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
                    label = ("Share of the reference topic's records held by "
                             + ", ".join(terms) + ", by year")
                    with ui.pyplot(figsize=(8, 4.4)).props(_figure_props(label)):
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
                job["busy"] = None
                cmp_btn.enable()

    # A magnifying glass rather than the framework's stock logo, which is what
    # a tab left open among others is identified by.
    ui.run(host=host, port=port, show=show, reload=reload, title="scopusflow",
           favicon="🔍")


def main(argv=None) -> None:
    """The ``scopusflow-gui`` console script.

    A thin argparse layer in front of :func:`launch`, so a flag is either
    honoured or rejected. Bound straight to ``launch``, the script read nothing
    from the command line, and ``scopusflow-gui --version`` silently started the
    GUI on the default port instead.
    """
    import argparse

    from . import __version__

    parser = argparse.ArgumentParser(
        prog="scopusflow-gui",
        description="Start the local scopusflow app in a browser.",
    )
    parser.add_argument("--version", action="version", version=f"scopusflow {__version__}")
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="interface to bind (default 127.0.0.1, reachable only from this machine)",
    )
    parser.add_argument("--port", type=int, default=8080, help="port to serve on (default 8080)")
    parser.add_argument(
        "--no-browser", action="store_true", help="do not open a browser window on start",
    )
    args = parser.parse_args(argv)
    launch(host=args.host, port=args.port, show=not args.no_browser)


if __name__ in {"__main__", "__mp_main__"}:
    main()
