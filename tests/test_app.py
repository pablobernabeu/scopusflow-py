"""Offline tests for the GUI: its pure helpers, and the page itself, built in
this process rather than served (no server, no network)."""

import ast
import logging
import pathlib

import pandas as pd
import pytest

from scopusflow.app_helpers import (
    app_busy_message,
    app_code_mirror,
    app_parse_progress,
    app_search_query,
    app_session_dir,
    app_years_code,
)


def test_app_years_code_renders_compact_expressions():
    assert app_years_code(range(2015, 2023)) == "range(2015, 2023)"
    assert app_years_code([2019]) == "[2019]"
    assert app_years_code([2010, 2012, 2015]) == "[2010, 2012, 2015]"
    assert app_years_code(None) is None
    assert app_years_code([]) is None


def test_app_search_query_trims_what_the_app_sends():
    # A query pasted from a document easily carries surrounding space. SearchPlan
    # validates with strip() but stores the value as typed, so untrimmed it goes
    # to the API inside the field tag and into the search record, while the
    # mirrored script shows the trimmed search.
    import scopusflow as sf

    typed = "  graphene supercapacitor  "
    assert app_search_query(typed) == "graphene supercapacitor"
    assert app_search_query(None) == ""
    sent = sf.SearchPlan(app_search_query(typed), field="TITLE-ABS-KEY").wrapped_query
    assert sent == "TITLE-ABS-KEY(graphene supercapacitor)"
    # The same expression the mirrored script has always shown.
    assert "sf.SearchPlan('graphene supercapacitor'" in app_code_mirror(query=typed)


def test_app_code_mirror_is_runnable_and_keyless():
    code = app_code_mirror(
        query="graphene supercapacitor", years=range(2018, 2023),
        field="TITLE-ABS-KEY", view="STANDARD", partition="year", by="source",
    )
    assert "import scopusflow as sf" in code
    assert "sf.SearchPlan(" in code
    assert "years=range(2018, 2023)" in code
    assert "field='TITLE-ABS-KEY'" in code
    assert "sf.fetch_plan(" in code
    assert "by='source'" in code
    # The script is valid Python and never contains a key.
    ast.parse(code)
    assert "key" not in code.lower() or "pybliometrics" in code


def test_app_code_mirror_marks_demo_mode_and_records_its_version():
    import scopusflow as sf

    live = app_code_mirror(query="graphene", years=range(2018, 2021))
    replayed = app_code_mirror(query="graphene", years=range(2018, 2021), demo=True)

    # The script pins the release that wrote it, whichever mode produced it.
    assert live.splitlines()[0] == f"# scopusflow {sf.__version__}"
    assert replayed.splitlines()[0] == f"# scopusflow {sf.__version__}"

    # Under a panel labelled "Reproducible Python", a demo script that says
    # nothing would reproduce a live harvest the user never ran.
    assert "example_records()" in replayed
    assert "example_records()" not in live
    # Both stay runnable Python, and neither carries a key.
    ast.parse(live)
    ast.parse(replayed)


def test_app_code_mirror_omits_absent_options():
    code = app_code_mirror(query="x", years=None, field=None,
                           view="STANDARD", partition="none")
    assert "years=" not in code
    assert "field=" not in code
    assert "partition=" not in code
    assert "COMPLETE" not in code
    ast.parse(code)


def test_app_code_mirror_partitions_only_when_asked_with_years():
    no_part = app_code_mirror(query="x", years=range(2018, 2021), partition="none")
    assert 'partition="year"' not in no_part
    with_part = app_code_mirror(query="x", years=range(2018, 2021), partition="year")
    assert 'partition="year"' in with_part


def test_app_code_mirror_appends_comparison_block_when_terms_given():
    code = app_code_mirror(
        query="deep learning", years=range(2018, 2023), field="TITLE-ABS-KEY",
        compare_terms=["computer vision", "drug discovery"],
        highlight="computer vision", interval=False, counts_in_legend=False,
    )
    assert "sf.compare_topics(" in code
    assert "'computer vision'" in code and "'drug discovery'" in code
    assert "sf.plot_comparison(" in code
    assert "highlight='computer vision'" in code
    assert "interval=False" in code
    assert "counts_in_legend=False" in code
    ast.parse(code)


def test_app_code_mirror_skips_comparison_without_terms_or_years():
    # No terms -> no compare block.
    assert "compare_topics" not in app_code_mirror(query="x", years=range(2018, 2021))
    # Terms but no span anywhere -> skipped (compare_topics needs an explicit span).
    assert "compare_topics" not in app_code_mirror(
        query="x", years=None, partition="none", compare_terms=["a"])


def test_app_code_mirror_compares_over_its_own_years_when_the_plan_has_none():
    # With "Partition by year" off the app still compares, over a default span,
    # so the mirrored script has to name that span rather than drop the block.
    code = app_code_mirror(query="x", years=None, partition="none",
                           compare_terms=["a"], compare_years=range(2020, 2026))
    assert "sf.compare_topics(" in code
    assert "years=range(2020, 2026)" in code
    assert "sf.SearchPlan('x')" in code  # and the plan itself stays unpartitioned
    ast.parse(code)


def test_demo_rows_come_from_the_bundled_harvest():
    import scopusflow as sf
    import scopusflow.app as app

    corpus = sf.example_records()
    rows = app._demo_rows(2019)
    # Uncapped, a cell is the whole year, so the demo trend is the real curve.
    assert len(rows) == 19
    assert {r["title"] for r in rows} <= set(corpus["title"])
    assert all(r["year"] == 2019 for r in rows)
    # Nothing invented: no Scopus identifiers, since the corpus carries none.
    assert all(pd.isna(r["scopus_id"]) for r in rows)


def test_demo_rows_handle_a_short_year_and_a_year_outside_the_corpus():
    import scopusflow as sf
    import scopusflow.app as app

    first, last = app._demo_year_span()
    assert (first, last) == (2015, 2024)
    assert len(app._demo_rows(2019, 5)) == 5  # capped when asked
    # 2016 holds nine records, so a request for more yields only those nine.
    assert len(app._demo_rows(2016, 40)) == 9
    # A year the corpus does not cover yields nothing rather than padding.
    assert app._demo_rows(last + 1) == []
    assert app._demo_rows(first - 1) == []
    assert len(sf.example_records()) == 138  # and the corpus is left intact


def test_demo_worker_replays_real_records_and_reports_empty_years(monkeypatch):
    import scopusflow as sf
    import scopusflow.app as app

    monkeypatch.setattr(app.time, "sleep", lambda *_: None)
    lines = []
    handler = logging.Handler()
    handler.emit = lambda r: lines.append(r.getMessage())
    logger = logging.getLogger("scopusflow")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        plan = sf.SearchPlan("graphene supercapacitor",
                             years=range(2023, 2026), partition="year")
        df = app._demo_worker(plan, lambda: False)
    finally:
        logger.removeHandler(handler)

    assert list(df.columns) == list(sf.RECORD_COLUMNS)
    assert len(df) == 29  # 2023 gives fifteen, 2024 fourteen, 2025 none
    assert df["entry_number"].tolist() == list(range(1, 30))
    assert df["title"].is_unique
    assert any("outside the bundled example harvest" in m for m in lines)


def test_the_demo_search_record_names_no_expression_and_says_it_was_replayed(monkeypatch):
    # The bundled corpus carries its own query, which is neither what the user
    # typed nor what the demo retrieved, and the record's methods paragraph is
    # written to be pasted into a manuscript.
    import scopusflow as sf
    import scopusflow.app as app

    monkeypatch.setattr(app.time, "sleep", lambda *_: None)
    plan = sf.SearchPlan("quantum dot photovoltaics", years=range(2018, 2021),
                         partition="year")
    records = app._demo_worker(plan, lambda: False)

    replayed = app._search_record(records, demo=True)
    assert "replayed from the bundled example harvest" in replayed
    assert "Search expression: unrecorded" in replayed
    assert "quantum dot photovoltaics" not in replayed
    assert "graphene supercapacitor" not in replayed
    # A real harvest's record is untouched, and the records keep their column.
    assert "graphene supercapacitor" in app._search_record(records, demo=False)
    assert records["query"].notna().all()


def test_demo_compare_worker_streams_parseable_progress(monkeypatch):
    import scopusflow.app as app

    monkeypatch.setattr(app.time, "sleep", lambda *_: None)  # no real delays in tests
    records = []
    handler = logging.Handler()
    handler.emit = lambda r: records.append(r.getMessage())
    logger = logging.getLogger("scopusflow")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        df = app._demo_compare_worker("graphene", ["a", "b"], [2019, 2020])
    finally:
        logger.removeHandler(handler)

    # One "Cell k/N" line per count step (reference + each term), in the form the
    # progress parser understands.
    assert any("Cell 1/3:" in m for m in records)
    assert any("Cell 3/3:" in m and "'b'" in m for m in records)
    assert app_parse_progress(["Cell 2/3: counting 'a'"]) == {"done": 2, "total": 3}
    assert (df["query_type"] == "comparison").any()


def test_app_busy_message_refuses_every_job_while_any_one_is_in_flight():
    # A harvest, a plan check and a comparison share the process-wide key and the
    # one "scopusflow" logger, so the exclusion has to run in every direction:
    # a comparison in flight used to leave "Fetch records" live, which crossed
    # the two log pumps and doubled the live API load.
    assert app_busy_message(None) is None
    for busy in ("fetch", "count", "compare"):
        assert app_busy_message(busy)
    assert "comparison" in app_busy_message("compare")
    assert "retrieval" in app_busy_message("fetch")


def test_the_download_script_is_not_named_after_the_package():
    import scopusflow.app as app

    # Saved as scopusflow.py, the downloaded script would sit first on sys.path
    # and shadow the package it imports, so it could not run where it landed.
    assert app._SCRIPT_FILENAME == "scopusflow-script.py"
    assert app._SCRIPT_FILENAME != f"{__import__('scopusflow').__name__}.py"


def test_fetch_worker_streams_an_incomplete_harvest_into_the_live_terminal(tmp_path):
    """A shortfall warning must reach the app, which only pumps the logger.

    A dependency's deprecation notice must not: the "always" filter un-hides
    those too, and one of them would turn a complete harvest amber.
    """
    import queue
    import sys
    import types
    import warnings

    import scopusflow as sf
    import scopusflow.app as app

    pybliometrics = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")

    class ScopusSearch:
        def __init__(self, query, **kwargs):
            # A dependency raising a deprecation notice on the way past,
            # attributed to this file rather than to the package. It is not the
            # app's to report: the harvest it accompanies is complete.
            warnings.warn("pandas: the 'foo' keyword is deprecated",
                          DeprecationWarning, stacklevel=1)
            self.results = [{
                "eid": "2-s2.0-85000000001", "doi": "10.1/a", "title": "A study",
                "author_names": "Smith J.", "coverDate": "2019-05-01",
                "publicationName": "Journal", "citedby_count": "3",
            }]

        def get_results_size(self):
            return 500  # the API says 500 match; one came back

    scopus.ScopusSearch = ScopusSearch
    pybliometrics.scopus = scopus
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}

    lines: queue.Queue = queue.Queue()
    handler = app._QueueHandler(lines)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("scopusflow")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        sys.modules["pybliometrics"] = pybliometrics
        sys.modules["pybliometrics.scopus"] = scopus
        plan = sf.SearchPlan("graphene", years=[2019], partition="year")
        records, warned = app._fetch_worker(plan, str(tmp_path), lambda: False)
    finally:
        logger.removeHandler(handler)
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    assert len(records) == 1
    # The warning is returned, so the completion notice can say so, and pumped
    # into the terminal rather than to the stderr of the process behind the tab.
    assert warned == [w for w in warned if "may be incomplete" in w]
    assert any("may be incomplete" in w for w in warned)
    drained = []
    while not lines.empty():
        drained.append(lines.get_nowait())
    assert any("may be incomplete" in line for line in drained)
    # The pump is left as it was found, ready for the next harvest.
    import warnings as _warnings
    assert _warnings.showwarning.__module__ != app.__name__


def test_the_console_script_honours_its_flags_and_refuses_unknown_ones(monkeypatch, capsys):
    import scopusflow as sf
    import scopusflow.app as app

    called = {}
    # launch() imports NiceGUI and starts a server, so only the parsing is
    # exercised here; the point is that the flags reach launch() at all.
    monkeypatch.setattr(app, "launch", lambda **kwargs: called.update(kwargs))

    app.main(["--port", "9000", "--host", "0.0.0.0", "--no-browser"])
    assert called == {"host": "0.0.0.0", "port": 9000, "show": False}

    with pytest.raises(SystemExit) as version:
        app.main(["--version"])
    assert version.value.code == 0
    assert sf.__version__ in capsys.readouterr().out

    # Bound straight to launch(), the script swallowed anything it was given.
    with pytest.raises(SystemExit) as unknown:
        app.main(["--nonsense"])
    assert unknown.value.code == 2


def test_app_session_dir_keeps_one_sessions_cleanup_out_of_anothers_cache(tmp_path):
    # The app's disconnect cleanup used to rmtree the shared temp base, so
    # closing one browser tab deleted another session's checkpoints mid-harvest.
    # Each page scope now works in its own subdirectory and removes only that.
    import shutil

    base = tmp_path / "scopusflow-app"
    a = pathlib.Path(app_session_dir(str(base)))
    b = pathlib.Path(app_session_dir(str(base)))
    assert a != b
    assert a.parent == base and b.parent == base

    (a / "digest").mkdir(parents=True)
    (b / "digest").mkdir(parents=True)
    (b / "digest" / "cell-001.csv").write_text("query\nx\n")
    shutil.rmtree(a, ignore_errors=True)   # session A's tab closes
    assert not a.exists()
    assert (b / "digest" / "cell-001.csv").exists()


def test_app_parse_progress_reads_latest_valid_marker():
    lines = ["Cell 1/8: fetching x (2018)", "Cell 2/8: fetching x (2019)"]
    assert app_parse_progress(lines) == {"done": 2, "total": 8}
    assert app_parse_progress([]) is None
    assert app_parse_progress(["no marker"]) is None
    # A "k/N" without the trailing colon (e.g. echoed in a query) is ignored.
    assert app_parse_progress(["fetching 'Cell 9/9 study'"]) is None
    # done > total is rejected.
    assert app_parse_progress(["Cell 9/2: bogus"]) is None


#: The arguments ``launch()`` hands ``ui.run``, kept by the stub _build_page
#: installs in its place.
_RUN_ARGUMENTS: dict = {}


def _build_page(monkeypatch):
    """Build the app's page in this process and return the elements it made.

    A NiceGUI page function is ordinary code that creates elements in the
    current client, so the page can be built without serving it, and the
    controls read back as the browser would receive them. Nothing here starts a
    server: ``ui.run`` is stubbed and ``ui.page`` only hands the page function
    back.
    """
    pytest.importorskip("nicegui")
    from nicegui import context, ui

    import scopusflow.app as app

    captured = {}

    def fake_page(path, **kwargs):
        def keep(function):
            captured["index"] = function
            return function
        return keep

    monkeypatch.setattr(ui, "page", fake_page)
    monkeypatch.setattr(ui, "run",
                        lambda *args, **kwargs: _RUN_ARGUMENTS.update(kwargs))
    app.launch(show=False)
    before = set(context.client.elements)
    captured["index"]()
    client = context.client
    return client, [e for i, e in client.elements.items() if i not in before]


def _of_type(elements, name):
    return [e for e in elements if type(e).__name__ == name]


def test_the_year_range_goes_with_the_partition_toggle(monkeypatch):
    # With partitioning off the range reaches neither the plan nor the
    # comparison, which falls back to its own six-year span, so a slider left on
    # screen reading 2015-2024 stated a span nothing was using.
    _, elements = _build_page(monkeypatch)
    partition = next(e for e in _of_type(elements, "Switch")
                     if e.text == "Partition by year (recommended)")
    years = _of_type(elements, "Range")[0]
    caption = next(e for e in _of_type(elements, "Label") if e.text == "Years")

    assert partition.value is True
    assert years.visible and caption.visible
    partition.value = False
    assert not years.visible and not caption.visible
    partition.value = True
    assert years.visible and caption.visible


def test_the_field_selector_can_leave_the_query_untagged(monkeypatch):
    # SearchPlan, scopus_count and compare_topics all take field=None, the code
    # mirror omits the argument for it, and the R twin's selector offers it, but
    # the Python selector had no entry that produced it, so every query the app
    # could issue was wrapped in a tag, including one the user had tagged by
    # hand.
    _, elements = _build_page(monkeypatch)
    field = next(e for e in _of_type(elements, "Select")
                 if e._props.get("label") == "Search in")
    code = _of_type(elements, "Code")[0]

    assert "(none)" in [option["label"] for option in field._props["options"]]
    assert "field='TITLE-ABS-KEY'" in code.content
    field.value = ""
    assert (field.value or None) is None
    assert "field=" not in code.content


def test_a_demo_harvest_tallies_authors_and_offers_the_dois(monkeypatch):
    # The R twin's app has a Top authors panel and a DOIs (.csv) download, and
    # both have direct Python equivalents, so their absence was the app's alone.
    pytest.importorskip("nicegui")
    pytest.importorskip("matplotlib")
    import asyncio

    from nicegui import core, run, ui

    async def straight_through(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(run, "io_bound", straight_through)
    client, elements = _build_page(monkeypatch)
    built = set(client.elements)
    # One year of the bundled corpus is one cell, so the replay is short.
    _of_type(elements, "Range")[0].value = {"min": 2019, "max": 2019}
    fetch = next(e for e in _of_type(elements, "Button") if e.text == "Fetch records")
    click = next(iter(fetch._event_listeners.values())).handler

    async def harvest():
        # So the click's task is run rather than deferred to a server start.
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        click(None)
        for _ in range(100):
            await asyncio.sleep(0.1)
            drawn = {i: e for i, e in client.elements.items() if i not in built}
            if any(type(e).__name__ == "Table" for e in drawn.values()):
                return drawn
        raise AssertionError("the demo harvest drew no record table")

    results = asyncio.run(harvest()).values()
    assert len(_of_type(results, "Pyplot")) == 3   # year trend, sources, authors

    saved = {}
    monkeypatch.setattr(ui.download, "content",
                        lambda content, filename: saved.update(text=content, name=filename))
    dois = next(e for e in _of_type(results, "Button") if e.text == "DOIs (.csv)")
    next(iter(dois._event_listeners.values())).handler(None)
    assert saved["name"] == "scopus-dois.csv"
    # One de-duplicated DOI a row under a doi header: the file the R twin's
    # DOIs button writes.
    rows = saved["text"].strip().splitlines()
    assert rows[0] == "doi"
    assert len(rows) - 1 == len(set(rows[1:])) > 0

    # Flipping Demo mode off leaves the results on screen, so the search record
    # has to keep describing the harvest that drew them.
    demo = next(e for e in _of_type(elements, "Switch")
                if e.text == "Demo mode (no key needed)")
    demo.value = False
    record = next(e for e in _of_type(results, "Button")
                  if e.text == "Search record (.md)")
    next(iter(record._event_listeners.values())).handler(None)
    assert saved["name"] == "scopus-search-record.md"
    assert "replayed from the bundled example harvest" in saved["text"]
    assert "Search expression: unrecorded" in saved["text"]
    assert "graphene supercapacitor" not in saved["text"]


def test_the_page_opens_on_the_state_the_guide_documents(monkeypatch):
    # Every default the app guide states, read off the built page: demo mode on
    # (so a visitor with no key sees a working flow), the year range opening on
    # the bundled corpus's own span (so every demo cell has records to replay),
    # the documented field tags, and the buttons the guide names. The R twin
    # pins the same span against its rendered UI.
    from scopusflow.app import _FIELD_CHOICES
    from scopusflow.data import example_records
    from scopusflow.query import FIELD_TAGS

    _, elements = _build_page(monkeypatch)
    switches = {e.text: e for e in _of_type(elements, "Switch")}
    inputs = {e._props.get("label"): e for e in _of_type(elements, "Input")}
    field = next(e for e in _of_type(elements, "Select")
                 if e._props.get("label") == "Search in")

    assert switches["Demo mode (no key needed)"].value is True
    assert switches["Partition by year (recommended)"].value is True
    assert inputs["Scopus API key"].value == ""
    assert _of_type(elements, "Radio")[0].value == "STANDARD"

    years = example_records()["year"]
    assert _of_type(elements, "Range")[0].value == {"min": int(years.min()),
                                                    "max": int(years.max())}

    # Every tagged entry is a tag the package documents, so a tag read off the
    # generated script can be looked up; the untagged entry is the app's own.
    assert field.value == "TITLE-ABS-KEY"
    labels = [option["label"] for option in field._props["options"]]
    assert labels[-1] == "(none)"
    tags = [t for t in _FIELD_CHOICES if t]
    assert [_FIELD_CHOICES[t] for t in tags] == labels[:-1]
    assert all(tag in FIELD_TAGS for tag in tags)

    buttons = {e.text for e in _of_type(elements, "Button")}
    assert {"Check plan", "Fetch records", "Cancel", "Compare topics",
            "Download script (.py)"} <= buttons

    # The panel mirrors the mode the click would run in, not a live harvest the
    # visitor never asked for.
    code = _of_type(elements, "Code")[0]
    assert "example_records" in code.content
    switches["Demo mode (no key needed)"].value = False
    assert "example_records" not in code.content


def test_no_click_spends_anything_without_a_key_or_terms(monkeypatch):
    # The guards that keep a click off the network, driven through the buttons
    # themselves rather than asserted of the helpers behind them. The R twin
    # covers the same three handlers through testServer.
    pytest.importorskip("nicegui")
    import asyncio

    from nicegui import core, run, ui

    async def refuse(function, *args, **kwargs):
        raise AssertionError(f"the app went out to {function!r}")

    monkeypatch.setattr(run, "io_bound", refuse)
    _, elements = _build_page(monkeypatch)
    notices = []
    monkeypatch.setattr(ui, "notify",
                        lambda message, **kwargs: notices.append(message))
    switches = {e.text: e for e in _of_type(elements, "Switch")}
    inputs = {e._props.get("label"): e for e in _of_type(elements, "Input")}
    buttons = {e.text: e for e in _of_type(elements, "Button") if e.text}
    # The one label the plan check writes into, told apart by its own class.
    size = next(e for e in _of_type(elements, "Label") if "text-grey-8" in e.classes)

    async def click(name):
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        next(iter(buttons[name]._event_listeners.values())).handler(None)
        await asyncio.sleep(0.2)
        return notices.pop()

    async def clicks():
        switches["Demo mode (no key needed)"].value = False
        for name in ("Check plan", "Fetch records", "Compare topics"):
            assert await click(name) == (
                "Enter your Scopus API key, or switch on Demo mode."
            )
        # A blank query is refused before anything is planned or counted, in
        # demo mode as well, where the whitespace would otherwise reach
        # SearchPlan and fail there after the user had waited.
        switches["Demo mode (no key needed)"].value = True
        inputs["Search terms"].value = "   "
        assert await click("Check plan") == "Enter search terms first."
        assert await click("Fetch records") == "Enter search terms first."
        assert await click("Compare topics") == (
            "Enter search terms first (used as the reference topic)."
        )
        # Nothing to cancel is said, rather than a harvest promised.
        next(iter(buttons["Cancel"]._event_listeners.values())).handler(None)
        assert notices.pop() == "Nothing to cancel."

    asyncio.run(clicks())
    assert not notices
    assert size.text == ""  # no plan was ever sized


def test_a_fetch_is_refused_while_a_comparison_is_in_flight(monkeypatch):
    # A harvest and a comparison share the process-wide key and the one
    # "scopusflow" logger, so a crossed pair doubles every terminal line and the
    # live request load. app_busy_message is pinned on its own; this drives the
    # exclusion through the buttons.
    pytest.importorskip("nicegui")
    pytest.importorskip("matplotlib")
    import asyncio

    from nicegui import core, run, ui

    client, elements = _build_page(monkeypatch)
    built = set(client.elements)
    notices = []
    monkeypatch.setattr(ui, "notify", lambda message, **kwargs: notices.append(message))
    buttons = {e.text: e for e in _of_type(elements, "Button") if e.text}

    def click(name):
        next(iter(buttons[name]._event_listeners.values())).handler(None)

    async def crossed():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        gate = asyncio.Event()

        async def held(function, *args, **kwargs):
            await gate.wait()
            return function(*args, **kwargs)

        monkeypatch.setattr(run, "io_bound", held)
        click("Compare topics")
        await asyncio.sleep(0.3)
        assert not buttons["Compare topics"].enabled
        click("Fetch records")
        await asyncio.sleep(0.3)
        assert notices == ["A topic comparison is already running."]
        drawn = {i: e for i, e in client.elements.items() if i not in built}
        assert not any(type(e).__name__ == "Table" for e in drawn.values())

        gate.set()
        for _ in range(100):
            await asyncio.sleep(0.1)
            drawn = {i: e for i, e in client.elements.items() if i not in built}
            if any(type(e).__name__ == "Pyplot" for e in drawn.values()):
                break
        else:
            raise AssertionError("the demo comparison drew no figure")
        # The flag is released with the comparison, so the next click is free.
        assert buttons["Compare topics"].enabled
        assert any(type(e).__name__ == "Button" and e.text == "Comparison (.csv)"
                   for e in drawn.values())

    asyncio.run(crossed())


def test_the_app_wears_the_family_palette(monkeypatch):
    # Everything the user clicks was painted in NiceGUI's stock blue, which
    # matches neither the R twin nor the documentation both apps sit behind, and
    # which white button text fails to clear at 3.06:1.
    from scopusflow.app import _BRAND_AMBER, _BRAND_INK, _BRAND_PRIMARY

    _, elements = _build_page(monkeypatch)
    palette = _of_type(elements, "Colors")[0]

    assert palette._props["primary"] == _BRAND_PRIMARY == "#0F6E6E"
    assert palette._props["secondary"] == _BRAND_INK
    assert palette._props["accent"] == _BRAND_AMBER
    # The button colour every card names, so nothing is left on the default.
    fetch = next(e for e in _of_type(elements, "Button") if e.text == "Fetch records")
    assert fetch._props["color"] == "primary"
    assert _RUN_ARGUMENTS["title"] == "scopusflow"
    assert _RUN_ARGUMENTS["favicon"]


def test_a_figure_name_survives_a_quotation_mark_in_the_terms():
    # The comparison figure is named after the terms in play, and NiceGUI parses
    # its props out of a string, so a quotation mark typed into the terms would
    # otherwise leave the figure with no name at all.
    pytest.importorskip("nicegui")
    from nicegui.props import Props

    from scopusflow.app import _figure_props

    parsed = Props.parse(_figure_props('Share held by "deep" learning, by year'))
    assert parsed["role"] == "img"
    assert parsed["aria-label"] == "Share held by deep learning, by year"


def test_the_figures_are_named_and_the_sections_are_headings(monkeypatch):
    # A NiceGUI figure is a div holding matplotlib's SVG, which carries no title
    # and no name, so a screen reader read loose tick labels or nothing; and the
    # two section titles, the page's only structure below its heading, were
    # plain labels.
    pytest.importorskip("nicegui")
    pytest.importorskip("matplotlib")
    import asyncio

    from nicegui import core, run

    async def straight_through(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(run, "io_bound", straight_through)
    client, elements = _build_page(monkeypatch)
    built = set(client.elements)
    assert "<h1>scopusflow</h1>" in _of_type(elements, "Markdown")[0]._props["innerHTML"]
    for title in ("Reproducible Python", "Compare topics"):
        label = next(e for e in _of_type(elements, "Label") if e.text == title)
        assert label._props["role"] == "heading"
        assert label._props["aria-level"] == "2"

    _of_type(elements, "Range")[0].value = {"min": 2019, "max": 2019}
    fetch = next(e for e in _of_type(elements, "Button") if e.text == "Fetch records")
    click = next(iter(fetch._event_listeners.values())).handler

    async def harvest():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        click(None)
        for _ in range(100):
            await asyncio.sleep(0.1)
            drawn = {i: e for i, e in client.elements.items() if i not in built}
            if any(type(e).__name__ == "Table" for e in drawn.values()):
                return drawn
        raise AssertionError("the demo harvest drew no record table")

    figures = _of_type(asyncio.run(harvest()).values(), "Pyplot")
    names = [f._props.get("aria-label") for f in figures]
    assert all(f._props.get("role") == "img" for f in figures)
    assert names == ["Records retrieved per year",
                     "The most frequent sources, by records retrieved",
                     "The most frequent authors, by records retrieved"]
    # The bar the harvest drives is on screen now that there is a run to report.
    assert _of_type(elements, "LinearProgress")[0].visible


def test_the_page_says_what_the_next_click_will_do(monkeypatch):
    # First-load feedback: the key state was readable only by pressing a button
    # and reading the warning, the harvest's progress bar sat at zero before
    # anything had run while the comparison's was hidden until used, the results
    # area was blank with nothing said, and a size note went on describing a
    # plan that had since been changed.
    pytest.importorskip("nicegui")
    import asyncio

    from nicegui import core

    _, elements = _build_page(monkeypatch)
    switches = {e.text: e for e in _of_type(elements, "Switch")}
    inputs = {e._props.get("label"): e for e in _of_type(elements, "Input")}
    buttons = {e.text: e for e in _of_type(elements, "Button") if e.text}
    status = next(e for e in _of_type(elements, "Label")
                  if e.text.startswith("Demo mode:"))
    size = next(e for e in _of_type(elements, "Label") if "text-grey-8" in e.classes)

    # Neither progress bar reports a job before one has run.
    assert not any(bar.visible for bar in _of_type(elements, "LinearProgress"))
    assert any(e.text == "Fetch records to see them here."
               for e in _of_type(elements, "Label"))

    assert status.text == ("Demo mode: real bundled records, simulated "
                           "comparison, no key needed.")
    switches["Demo mode (no key needed)"].value = False
    assert status.text == "Enter your key to fetch."
    inputs["Scopus API key"].value = "a-key"
    assert status.text == "Key set."
    switches["Demo mode (no key needed)"].value = True

    async def check_plan():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        next(iter(buttons["Check plan"]._event_listeners.values())).handler(None)
        await asyncio.sleep(0.2)

    asyncio.run(check_plan())
    assert size.text.startswith("Demo plan:")
    # The note answered for the plan that was checked, so the plan changing
    # drops it rather than leaving it to describe a search nobody asked about.
    inputs["Search terms"].value = "graphene aerogel"
    assert size.text == ""
