"""Offline tests for the GUI's pure helpers, and for one demo harvest driven on
the page built in this process, which needs NiceGUI and skips without it (no
server, no network)."""

import ast
import logging
import pathlib
import re
import sys
import types
import warnings

import pandas as pd
import pytest

from scopusflow.app_helpers import (
    app_code_mirror,
    app_comparison_cost,
    app_fetch_notice,
    app_parse_progress,
    app_session_dir,
    app_years_code,
)


def test_app_years_code_renders_compact_expressions():
    assert app_years_code(range(2015, 2023)) == "range(2015, 2023)"
    assert app_years_code([2019]) == "[2019]"
    assert app_years_code([2010, 2012, 2015]) == "[2010, 2012, 2015]"
    assert app_years_code(None) is None
    assert app_years_code([]) is None


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


def test_the_script_initialises_pybliometrics_without_a_key_in_it():
    # pybliometrics 4 raises at the first search of a session that has not
    # called init(). The script used to suggest init(keys=[...]), which invites
    # pasting the key into the very file the panel is there to share.
    for demo in (False, True):
        code = app_code_mirror(query="graphene", years=range(2018, 2021), demo=demo)
        lines = code.splitlines()
        assert "import pybliometrics" in lines
        assert "pybliometrics.init()" in lines
        assert "init(keys" not in code
        assert lines.index("pybliometrics.init()") < next(
            i for i, line in enumerate(lines) if "sf.fetch_plan(" in line
        )
        ast.parse(code)


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


def test_app_code_mirror_compares_over_the_apps_years_when_the_plan_has_none():
    # With "Partition by year" off the app still compares, over the last six
    # years, so the script has to name that span where it used to drop the block.
    code = app_code_mirror(query="x", years=None, partition="none",
                           compare_terms=["a"], compare_years=range(2021, 2027))
    assert "sf.compare_topics(" in code
    assert "years=range(2021, 2027)" in code
    assert "sf.SearchPlan('x')" in code  # and the plan itself stays unpartitioned
    ast.parse(code)


def test_the_app_hands_the_script_the_years_it_compares():
    # The panel is drawn inside a running NiceGUI page, so the call is read from
    # the source: the script must be given the comparison's span.
    import scopusflow.app as app

    tree = ast.parse(pathlib.Path(app.__file__).read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "app_code_mirror"]
    assert len(calls) == 1
    assert "compare_years" in {kw.arg for kw in calls[0].keywords}


def test_a_comparison_costs_a_request_per_term_and_one_for_the_reference_each_year():
    # compare_topics() counts the reference in every year as well as each term,
    # so the app's default of two terms over six years makes 18 requests.
    assert app_comparison_cost(2, 6) == 18
    assert app_comparison_cost(1, 1) == 2


def _script_cache_dir(code):
    """The directory a generated script passes to ``fetch_plan``."""
    (found,) = re.findall(r"cache_dir='([^']*)'", code)
    return found


def test_each_plan_gets_a_checkpoint_directory_of_its_own():
    def name(**kwargs):
        return _script_cache_dir(app_code_mirror(**kwargs))

    base = name(query="graphene", years=range(2018, 2023), field="TITLE-ABS-KEY")
    assert re.fullmatch(r"harvest-[0-9a-f]{8}", base)
    # The same search finds its checkpoints again.
    assert name(query="graphene", years=range(2018, 2023), field="TITLE-ABS-KEY") == base
    # Whatever changes the cells changes the directory.
    others = [
        name(query="graphene oxide", years=range(2018, 2023), field="TITLE-ABS-KEY"),
        name(query="graphene", years=range(2019, 2023), field="TITLE-ABS-KEY"),
        name(query="graphene", years=range(2018, 2023), field="TITLE"),
        name(query="graphene", years=range(2018, 2023), field="TITLE-ABS-KEY",
             view="COMPLETE"),
        name(query="graphene", years=range(2018, 2023), field="TITLE-ABS-KEY",
             partition="none"),
    ]
    assert base not in others
    assert len(set(others)) == len(others)


def _guide_value(node):
    """A literal, or a ``range()`` of literals, from a code block in a guide."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "range"):
        return range(*(ast.literal_eval(arg) for arg in node.args))
    return ast.literal_eval(node)


def test_the_app_guide_shows_the_directory_the_script_names():
    # The guide prints the panel's script for its example search, so each
    # directory it shows has to be the one the script names for the plan printed
    # beside it. The plan is read from the block itself, so a guide whose search
    # changes cannot keep the old search's directory.
    guide = pathlib.Path(__file__).resolve().parents[1] / "docs" / "guides" / "the-app.md"
    if not guide.exists():
        pytest.skip("the guides are not part of this checkout")
    blocks = [block for block in re.findall(r"```python\n(.*?)```",
                                            guide.read_text(encoding="utf-8"), re.S)
              if "fetch_plan(" in block]
    assert len(blocks) == 2
    for block in blocks:
        calls = {node.func.attr: node for node in ast.walk(ast.parse(block))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        plan = calls["SearchPlan"]
        args = {kw.arg: _guide_value(kw.value) for kw in plan.keywords}
        shown = {kw.arg: _guide_value(kw.value) for kw in calls["fetch_plan"].keywords}
        # SearchPlan's own defaults, where the block leaves an argument out.
        code = app_code_mirror(query=_guide_value(plan.args[0]),
                               years=args.get("years"), field=args.get("field"),
                               view=args.get("view", "STANDARD"),
                               partition=args.get("partition", "none"))
        assert re.fullmatch(r"harvest-[0-9a-f]{8}", shown["cache_dir"])
        assert shown["cache_dir"] == _script_cache_dir(code)


def _run_script_harvest(code):
    """Run the two statements of a generated script that reach the cache, the
    plan and the fetch. The others size, save, tally or plot."""
    import scopusflow as sf

    keep = [node for node in ast.parse(code).body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr in ("SearchPlan", "fetch_plan")]
    namespace = {"sf": sf}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "<script>", "exec"), namespace)
    return namespace["records"]


def test_the_scripts_the_app_writes_keep_each_plans_checkpoints_apart(monkeypatch, tmp_path):
    sent = []

    class _Search:
        def __init__(self, query, **kwargs):
            sent.append(query)
            self.results = [{"eid": "2-s2.0-1", "doi": "10.1/a", "coverDate": "2023-05-01"}]

        def get_results_size(self):
            return 1

    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.ScopusSearch = _Search
    pkg = types.ModuleType("pybliometrics")
    pkg.scopus = scopus
    monkeypatch.setitem(sys.modules, "pybliometrics", pkg)
    monkeypatch.setitem(sys.modules, "pybliometrics.scopus", scopus)
    monkeypatch.chdir(tmp_path)  # the script's cache directory is relative

    first = app_code_mirror(query="graphene", years=range(2023, 2025))
    second = app_code_mirror(query="perovskite", years=range(2023, 2025))
    _run_script_harvest(first)
    _run_script_harvest(second)
    assert len(sent) == 4
    # Every script used to pass cache_dir='harvest', where the second plan's
    # cells overwrote the first plan's, so each rerun refetched them with a
    # warning.
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        _run_script_harvest(first)
    assert len(sent) == 4


def _download_names():
    """Every file name the app hands to ``ui.download.content``, read from its
    source, since the buttons only exist inside a running NiceGUI page."""
    import scopusflow.app as app

    tree = ast.parse(pathlib.Path(app.__file__).read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "content"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "download"):
            continue
        given = [kw.value for kw in node.keywords if kw.arg == "filename"]
        target = node.args[1] if len(node.args) > 1 else given[0]
        if isinstance(target, ast.Constant):
            names.append(target.value)
        elif isinstance(target, ast.Name):
            names.append(getattr(app, target.id))
        else:
            raise AssertionError(f"Unexpected download name: {ast.dump(target)}")
    return names


def test_the_downloaded_script_cannot_shadow_the_package():
    # Python puts a script's own folder first on sys.path. The script saved as
    # scopusflow.py therefore imported itself when run where it landed, and
    # stopped with an AttributeError at the first attribute it read from the
    # package. No import statement can name a file whose stem is not an
    # identifier.
    scripts = [name for name in _download_names() if name.endswith(".py")]
    assert scripts, "the app no longer offers its script for download"
    for name in scripts:
        assert name != "scopusflow.py"
        assert not pathlib.Path(name).stem.isidentifier()

    # The R twin's app saves the same script as scopusflow-script.R.
    assert scripts == ["scopusflow-script.py"]


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
    # It ran every cell, so it records no stop.
    assert "stopped_early" not in df.attrs


def test_demo_worker_records_a_cancel_as_fetch_plan_does(monkeypatch):
    import scopusflow as sf
    import scopusflow.app as app

    monkeypatch.setattr(app.time, "sleep", lambda *_: None)
    calls = []

    def should_stop():
        calls.append(1)
        return len(calls) > 2  # checked before each cell: two run, the third stops

    plan = sf.SearchPlan("graphene supercapacitor", years=range(2016, 2021),
                         partition="year")
    df = app._demo_worker(plan, should_stop)
    assert len(df) == 19  # 2016 gives nine, 2017 ten
    assert df.attrs["stopped_early"] is True
    assert df.attrs["cells_planned"] == 5
    assert df.attrs["cells_run"] == 2
    assert app_fetch_notice(df) == ("Stopped after 2 of 5 cells.", "warning")


def test_the_notice_after_a_harvest_says_when_it_was_stopped():
    # Cancel used to end on "Retrieved N records.", as if the harvest were whole.
    records = pd.DataFrame({"title": ["a", "b"]})
    assert app_fetch_notice(records) == ("Retrieved 2 records.", "positive")
    assert app_fetch_notice(records.iloc[0:0]) == ("Retrieved 0 records.", "warning")
    records.attrs.update(stopped_early=True, cells_planned=5, cells_run=2)
    assert app_fetch_notice(records) == ("Stopped after 2 of 5 cells.", "warning")
    single = pd.DataFrame({"title": []})
    single.attrs.update(stopped_early=True, cells_planned=1, cells_run=0)
    assert app_fetch_notice(single) == ("Stopped after 0 of 1 cell.", "warning")
    many = pd.DataFrame({"title": ["x"] * 1234})
    assert app_fetch_notice(many) == ("Retrieved 1,234 records.", "positive")


def test_the_demo_search_record_names_no_expression_and_says_it_was_replayed(monkeypatch):
    # The bundled corpus carries the phrase of its own OpenAlex search in its
    # query column, which is neither what the user typed nor a search sent to
    # Scopus. Carried into the record, it was the search expression of a
    # methods paragraph written to be pasted into a manuscript. The R twin's
    # app_search_record() writes the same note.
    import scopusflow as sf
    import scopusflow.app as app

    monkeypatch.setattr(app.time, "sleep", lambda *_: None)
    plan = sf.SearchPlan("quantum dot photovoltaics", years=range(2018, 2021),
                         partition="year")
    records = app._demo_worker(plan, lambda: False)

    replayed = app._search_record(records, replayed=True)
    assert replayed.startswith("> Demo mode: these records were replayed from the "
                               "bundled example harvest")
    assert "describes no search that was run" in " ".join(replayed.split())
    assert "Search expression: unrecorded" in replayed
    assert "quantum dot photovoltaics" not in replayed
    assert "graphene supercapacitor" not in replayed
    # A live harvest's record is the one scopus_search_report writes, and the
    # records on screen keep their query column.
    live = app._search_record(records, replayed=False)
    assert live == sf.scopus_search_report(records).format(style="markdown")
    assert records["query"].notna().all()


# The demo's source titles are too long for tight_layout to fit beside the bars.
@pytest.mark.filterwarnings("ignore:Tight layout not applied:UserWarning")
def test_switching_demo_mode_off_during_a_demo_harvest_leaves_it_replayed(monkeypatch):
    # The records stay on screen when Demo mode is switched off during the run
    # or after it, so the label above them and the search record have to keep
    # describing the harvest that drew them. The mode is therefore fixed when
    # Fetch is clicked, as the R twin's server fixes it when the harvest starts.
    # The page is built in this process and never served: ui.run is stubbed and
    # ui.page only hands the page function back.
    pytest.importorskip("nicegui")
    pytest.importorskip("matplotlib")
    import asyncio

    from nicegui import context, core, run, ui

    import scopusflow.app as app

    page = {}

    def fake_page(path, **kwargs):
        def keep(function):
            page["index"] = function
            return function
        return keep

    async def straight_through(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(ui, "page", fake_page)
    monkeypatch.setattr(ui, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(run, "io_bound", straight_through)
    monkeypatch.setattr(app.time, "sleep", lambda *_: None)
    app.launch(show=False)
    client = context.client
    before = set(client.elements)
    page["index"]()
    elements = [e for i, e in client.elements.items() if i not in before]

    def find(elements, kind, text):
        return next(e for e in elements
                    if type(e).__name__ == kind and getattr(e, "text", None) == text)

    def handler(element):
        listeners = getattr(element, "_event_listeners", None)
        if not listeners:
            pytest.skip("this NiceGUI keeps an element's event handlers elsewhere")
        return next(iter(listeners.values())).handler

    demo = find(elements, "Switch", "Demo mode (no key needed)")
    assert demo.value is True
    # One year of the bundled corpus is one cell, so the replay is short.
    next(e for e in elements if type(e).__name__ == "Range").value = {"min": 2019, "max": 2019}
    replay = app._demo_worker

    def switched_off_during_the_run(plan, should_stop):
        demo.value = False
        return replay(plan, should_stop)

    monkeypatch.setattr(app, "_demo_worker", switched_off_during_the_run)
    click = handler(find(elements, "Button", "Fetch records"))
    built = set(client.elements)

    async def harvest():
        # So the click's task runs on this loop, not deferred to a server start.
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        click(None)
        for _ in range(200):
            await asyncio.sleep(0.05)
            drawn = [e for i, e in client.elements.items() if i not in built]
            if any(type(e).__name__ == "Table" for e in drawn):
                return drawn
        raise AssertionError("the demo harvest drew no record table")

    results = asyncio.run(harvest())
    assert demo.value is False
    assert any(type(e).__name__ == "Label" and e.text.startswith(
        "Demo mode: these records were replayed") for e in results)

    saved = {}
    monkeypatch.setattr(ui.download, "content",
                        lambda content, filename: saved.update(text=content, name=filename))
    handler(find(results, "Button", "Search record (.md)"))(None)
    assert saved["name"] == "scopus-search-record.md"
    assert saved["text"].startswith("> Demo mode: these records were replayed")
    assert "Search expression: unrecorded" in saved["text"]
    assert "graphene supercapacitor" not in saved["text"]


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


def test_the_demo_comparison_joins_its_queries_as_compare_topics_does():
    import scopusflow.app as app

    df = app._demo_comparison("a OR b", ["c d"], [2019, 2020])
    comparison = df[df["query_type"] == "comparison"]
    assert set(comparison["query"]) == {"(a OR b) AND (c d)"}


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


PASTED = "PASTED-KEY-0000"


@pytest.fixture
def pyb_home(tmp_path, monkeypatch):
    """The real pybliometrics, with every path it would touch under ``tmp_path``.

    Its configuration file, its default cache folders and the temporary
    directory the app creates are all redirected, and its process-global state
    is restored afterwards, so neither the user's own configuration nor
    ``~/.cache`` is read or written.
    """
    import sys
    import tempfile

    # Other tests put stand-in modules under these names. Each restores what it
    # replaced, but none may stand in for the real package here.
    for name in [n for n in list(sys.modules)
                 if n == "pybliometrics" or n.startswith("pybliometrics.")]:
        if getattr(sys.modules[name], "__file__", None) is None:
            monkeypatch.delitem(sys.modules, name)
    pytest.importorskip("pybliometrics.scopus")
    from pybliometrics.utils import constants, startup

    import scopusflow.app as app

    config_file = tmp_path / "home" / ".config" / "pybliometrics.cfg"
    defaults = {api: tmp_path / "home" / ".cache" / api for api in constants.DEFAULT_PATHS}
    # init() reads startup's own binding of CONFIG_FILE and DEFAULT_PATHS, and
    # create_config() reads constants', so both are redirected.
    for module in (startup, constants):
        monkeypatch.setattr(module, "CONFIG_FILE", config_file)
        monkeypatch.setattr(module, "DEFAULT_PATHS", defaults)
    for name in ("CONFIG", "CUSTOM_KEYS", "CUSTOM_INSTTOKENS"):
        monkeypatch.setattr(startup, name, getattr(startup, name))
    temp = tmp_path / "tmp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    monkeypatch.setattr(app, "_PYB_DIR", None, raising=False)
    yield {"config_file": config_file, "temp": temp, "startup": startup}
    remove = getattr(app, "_remove_pyb_dir", None)
    if remove is not None:
        remove()


def _files_holding(root, text):
    needle = text.encode("utf-8")
    return [p for p in pathlib.Path(root).rglob("*")
            if p.is_file() and needle in p.read_bytes()]


def test_a_pasted_key_is_never_written_where_no_configuration_exists(pyb_home, tmp_path):
    # pybliometrics' init(keys=[...]) creates a missing configuration file and
    # writes the key into it in plain text, which the app's guide and
    # SECURITY.md both said would never happen.
    import scopusflow.app as app

    startup = pyb_home["startup"]
    app._init_key(PASTED)

    assert startup.get_keys() == [PASTED]
    assert not pyb_home["config_file"].exists()
    assert _files_holding(tmp_path, PASTED) == []
    assert not (tmp_path / "home" / ".cache").exists()

    # pybliometrics is given a key-less configuration in one directory for the
    # whole process, and every folder it names lies under that directory, so
    # no response outlives the app.
    (process_dir,) = [p for p in pyb_home["temp"].iterdir()
                      if p.name.startswith("scopusflow-app-pybliometrics-")]
    directories = dict(startup.CONFIG.items("Directories"))
    assert set(directories) >= set(startup.DEFAULT_PATHS)
    for path in directories.values():
        assert pathlib.Path(path).resolve().is_relative_to(process_dir.resolve())

    # A second key in the same process reuses the directory.
    app._init_key("SECOND-KEY-0000")
    assert startup.get_keys() == ["SECOND-KEY-0000"]
    assert [p for p in pyb_home["temp"].iterdir()] == [process_dir]
    assert _files_holding(tmp_path, "SECOND-KEY-0000") == []

    app._remove_pyb_dir()
    assert not process_dir.exists()


def test_a_pasted_key_leaves_an_existing_configuration_as_it_was(pyb_home, tmp_path):
    from configparser import ConfigParser

    import scopusflow.app as app

    startup = pyb_home["startup"]
    config = ConfigParser()
    config.optionxform = str
    config.add_section("Directories")
    for api in startup.DEFAULT_PATHS:
        config.set("Directories", api, str(tmp_path / "own-cache" / api))
    config.add_section("Authentication")
    config.set("Authentication", "APIKey", "USERS-OWN-KEY")
    config.add_section("Requests")
    pyb_home["config_file"].parent.mkdir(parents=True)
    with open(pyb_home["config_file"], "w", encoding="utf-8") as fh:
        config.write(fh)
    before = pyb_home["config_file"].read_text(encoding="utf-8")

    app._init_key(PASTED)

    assert startup.get_keys() == [PASTED]
    assert pyb_home["config_file"].read_text(encoding="utf-8") == before
    assert "APIKey = USERS-OWN-KEY" in before
    assert _files_holding(tmp_path, PASTED) == []
    # The user's own configuration is used as it stands, so no temporary one
    # is made.
    assert list(pyb_home["temp"].iterdir()) == []


def test_app_parse_progress_reads_latest_valid_marker():
    lines = ["Cell 1/8: fetching x (2018)", "Cell 2/8: fetching x (2019)"]
    assert app_parse_progress(lines) == {"done": 2, "total": 8}
    assert app_parse_progress([]) is None
    assert app_parse_progress(["no marker"]) is None
    # A "k/N" without the trailing colon (e.g. echoed in a query) is ignored.
    assert app_parse_progress(["fetching 'Cell 9/9 study'"]) is None
    # done > total is rejected.
    assert app_parse_progress(["Cell 9/2: bogus"]) is None


def test_app_busy_message_refuses_every_job_while_any_one_is_in_flight():
    # A harvest, a plan check and a comparison share the process-wide key and
    # the one "scopusflow" logger, so the refusal runs in every direction.
    from scopusflow.app_helpers import app_busy_message

    assert app_busy_message(None) is None
    assert app_busy_message("fetch") == "A retrieval is already running."
    assert app_busy_message("count") == "A plan check is already running."
    assert app_busy_message("compare") == "A topic comparison is already running."


def test_app_search_query_trims_what_the_app_sends():
    # SearchPlan checks the query with strip() but keeps it as typed, so a query
    # pasted with surrounding space went to the API inside the field tag while
    # the script panel showed it trimmed.
    import scopusflow as sf
    from scopusflow.app_helpers import app_search_query

    typed = "  graphene supercapacitor\t"
    assert app_search_query(typed) == "graphene supercapacitor"
    assert app_search_query(None) == ""
    plan = sf.SearchPlan(app_search_query(typed), field="TITLE-ABS-KEY")
    assert plan.wrapped_query == "TITLE-ABS-KEY(graphene supercapacitor)"
    assert "sf.SearchPlan('graphene supercapacitor'" in app_code_mirror(query=typed)


def test_the_notice_after_a_harvest_says_when_it_may_be_incomplete():
    # fetch_plan reports a short cell through a warning, which the app used to
    # leave on the stderr of the process behind the tab while announcing the
    # harvest in green.
    records = pd.DataFrame({"title": ["a", "b"]})
    shortfall = ("Cell 1 retrieved 2 record(s), but the Scopus API reports 10 for "
                 "this query, so the harvest may be incomplete.")
    message, kind = app_fetch_notice(records, warned=[shortfall])
    assert kind == "warning"
    assert message == f"Retrieved 2 records, but the harvest may be incomplete. {shortfall}"
    assert app_fetch_notice(records, warned=[]) == ("Retrieved 2 records.", "positive")
    # A stop is the first thing to say about a harvest that stopped.
    records.attrs.update(stopped_early=True, cells_planned=5, cells_run=2)
    assert app_fetch_notice(records, warned=[shortfall]) == (
        "Stopped after 2 of 5 cells.", "warning")


def test_the_harvest_streams_its_warnings_into_the_live_terminal(tmp_path):
    """A shortfall warning reaches the app, which only pumps the logger. A
    dependency's deprecation notice does not: the "always" filter the worker
    sets un-hides those too, and one would turn a complete harvest amber."""
    import queue

    import scopusflow as sf
    import scopusflow.app as app

    pybliometrics = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")

    class ScopusSearch:
        def __init__(self, query, **kwargs):
            # Raised from this file, outside the package, so not the app's to
            # report.
            warnings.warn("pandas: the 'foo' keyword is deprecated",
                          DeprecationWarning, stacklevel=1)
            self.results = [{
                "eid": "2-s2.0-85000000001", "doi": "10.1/a", "title": "A study",
                "author_names": "Smith J.", "coverDate": "2019-05-01",
                "publicationName": "Journal", "citedby_count": "3",
            }]

        def get_results_size(self):
            return 500  # the API says 500 match, and one came back

    scopus.ScopusSearch = ScopusSearch
    pybliometrics.scopus = scopus
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    shown_before = warnings.showwarning
    lines: queue.Queue = queue.Queue()
    handler = app._QueueHandler(lines)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("scopusflow")
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        sys.modules["pybliometrics"] = pybliometrics
        sys.modules["pybliometrics.scopus"] = scopus
        plan = sf.SearchPlan("graphene", years=[2019], partition="year")
        records, warned = app._fetch_worker(plan, str(tmp_path), lambda: False)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    assert len(records) == 1
    assert len(warned) == 1 and "may be incomplete" in warned[0]
    drained = []
    while not lines.empty():
        drained.append(lines.get_nowait())
    assert any("may be incomplete" in line for line in drained)
    assert not any("deprecated" in line for line in drained)
    # The warning machinery is left as it was found.
    assert warnings.showwarning is shown_before


# ---- The page, built in this process --------------------------------------

def _build_page(monkeypatch):
    """Build the app's page in this process and return the client and the
    elements it made. Nothing is served: ``ui.run`` is stubbed and ``ui.page``
    only hands the page function back, as in the demo-harvest test above."""
    pytest.importorskip("nicegui")
    from nicegui import context, ui

    import scopusflow.app as app

    page = {}

    def fake_page(path, **kwargs):
        def keep(function):
            page["index"] = function
            return function
        return keep

    monkeypatch.setattr(ui, "page", fake_page)
    monkeypatch.setattr(ui, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(app.time, "sleep", lambda *_: None)
    app.launch(show=False)
    client = context.client
    before = set(client.elements)
    page["index"]()
    return client, [e for i, e in client.elements.items() if i not in before]


def _of_type(elements, name):
    return [e for e in elements if type(e).__name__ == name]


def _click(element):
    listeners = getattr(element, "_event_listeners", None)
    if not listeners:
        pytest.skip("this NiceGUI keeps an element's event handlers elsewhere")
    next(iter(listeners.values())).handler(None)


def _contrast(foreground: str, background: str) -> float:
    """The WCAG 2 contrast ratio of two #RRGGBB colours."""
    def luminance(colour):
        channels = [int(colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                  for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    high, low = sorted([luminance(foreground), luminance(background)], reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_one_job_runs_at_a_time(monkeypatch):
    # A harvest and a comparison drive the same key and the one "scopusflow"
    # logger, so a crossed pair fed each other's progress into both log pumps
    # and doubled the live request load. Only a running harvest was refused, so
    # Fetch records stayed live during a comparison, and a comparison could be
    # started twice.
    pytest.importorskip("nicegui")
    pytest.importorskip("matplotlib")
    import asyncio

    from nicegui import core, run, ui

    client, elements = _build_page(monkeypatch)
    built = set(client.elements)
    notices = []
    monkeypatch.setattr(ui, "notify", lambda message, **kwargs: notices.append(message))
    buttons = {e.text: e for e in _of_type(elements, "Button") if e.text}

    async def crossed():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        gate = asyncio.Event()

        async def held(function, *args, **kwargs):
            await gate.wait()
            return function(*args, **kwargs)

        monkeypatch.setattr(run, "io_bound", held)
        _click(buttons["Compare topics"])
        await asyncio.sleep(0.3)
        for name in ("Fetch records", "Check plan", "Compare topics"):
            _click(buttons[name])
        await asyncio.sleep(0.3)
        refused = list(notices)
        gate.set()
        for _ in range(100):
            await asyncio.sleep(0.1)
            drawn = [e for i, e in client.elements.items() if i not in built]
            if _of_type(drawn, "Pyplot"):
                return refused, drawn
        raise AssertionError("the demo comparison drew no figure")

    refused, drawn = asyncio.run(crossed())
    assert refused == ["A topic comparison is already running."] * 3
    assert not _of_type(drawn, "Table")
    # The comparison releases the app when it ends.
    assert buttons["Compare topics"].enabled


def test_the_app_sends_the_query_it_shows(monkeypatch):
    pytest.importorskip("nicegui")
    import asyncio

    from nicegui import core, run, ui

    import scopusflow as sf
    import scopusflow.app as app

    sent = []

    async def capture(function, *args, **kwargs):
        sent.append((getattr(function, "__name__", ""), args))
        if function is sf.scopus_count:
            return 10
        if function is sf.compare_topics:
            return app._demo_comparison(args[0], args[1], args[2])
        records = app._demo_worker(args[0], lambda: False)
        return records if function is sf.fetch_plan else (records, [])

    monkeypatch.setattr(run, "io_bound", capture)
    monkeypatch.setattr(app, "_init_key", lambda key: None)
    _, elements = _build_page(monkeypatch)
    monkeypatch.setattr(ui, "notify", lambda *args, **kwargs: None)
    switches = {e.text: e for e in _of_type(elements, "Switch")}
    inputs = {e._props.get("label"): e for e in _of_type(elements, "Input")}
    buttons = {e.text: e for e in _of_type(elements, "Button") if e.text}
    switches["Demo mode (no key needed)"].value = False
    inputs["Scopus API key"].value = "a-key"
    inputs["Search terms"].value = "  graphene supercapacitor\t"
    _of_type(elements, "Range")[0].value = {"min": 2019, "max": 2019}

    async def clicks():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        for name in ("Check plan", "Fetch records", "Compare topics"):
            _click(buttons[name])
            await asyncio.sleep(0.5)

    asyncio.run(clicks())
    calls = dict(sent)
    assert calls["scopus_count"][0] == "graphene supercapacitor"
    plan = (calls.get("_fetch_worker") or calls["fetch_plan"])[0]
    assert plan.query == "graphene supercapacitor"
    assert calls["compare_topics"][0] == "graphene supercapacitor"


def test_a_figure_that_cannot_be_drawn_leaves_the_records_and_the_exports(monkeypatch):
    # Showing the records is not retrieving them. A figure that failed took the
    # export buttons with it and was announced as a retrieval that did not
    # complete, so a harvest that had been paid for could only be had again by
    # paying for it a second time.
    pytest.importorskip("nicegui")
    pytest.importorskip("matplotlib")
    import asyncio

    from nicegui import core, run, ui

    import scopusflow as sf

    async def straight_through(function, *args, **kwargs):
        return function(*args, **kwargs)

    def unplottable(*args, **kwargs):
        raise ValueError("The trend has no years to plot.")

    monkeypatch.setattr(run, "io_bound", straight_through)
    monkeypatch.setattr(sf, "plot_trend", unplottable)
    client, elements = _build_page(monkeypatch)
    notices = []
    monkeypatch.setattr(ui, "notify", lambda message, **kwargs: notices.append(message))
    built = set(client.elements)
    _of_type(elements, "Range")[0].value = {"min": 2019, "max": 2019}
    fetch = next(e for e in _of_type(elements, "Button") if e.text == "Fetch records")

    async def harvest():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        _click(fetch)
        for _ in range(100):
            await asyncio.sleep(0.1)
            if any("records" in m.lower() for m in notices):
                break
        return [e for i, e in client.elements.items() if i not in built]

    drawn = asyncio.run(harvest())
    assert {"Records (.csv)", "BibTeX (.bib)", "RIS (.ris)",
            "Search record (.md)"} <= {e.text for e in _of_type(drawn, "Button")}
    assert any(e.text.startswith("No trend to plot") for e in _of_type(drawn, "Label"))
    assert not any("did not complete" in m for m in notices)


def test_a_size_note_goes_when_the_plan_changes(monkeypatch):
    # The note answered for the plan that was checked, and stayed on screen when
    # the plan changed, as though it priced the new one.
    pytest.importorskip("nicegui")
    import asyncio

    from nicegui import core

    _, elements = _build_page(monkeypatch)
    inputs = {e._props.get("label"): e for e in _of_type(elements, "Input")}
    buttons = {e.text: e for e in _of_type(elements, "Button") if e.text}
    size = next(e for e in _of_type(elements, "Label") if "text-grey-8" in e.classes)

    async def check_plan():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        _click(buttons["Check plan"])
        await asyncio.sleep(0.2)

    asyncio.run(check_plan())
    assert size.text.startswith("Demo plan:")
    inputs["Search terms"].value = "graphene aerogel"
    assert size.text == ""
    asyncio.run(check_plan())
    _of_type(elements, "Range")[0].value = {"min": 2018, "max": 2020}
    assert size.text == ""


def test_the_year_range_goes_with_the_partition_toggle(monkeypatch):
    # With partitioning off the range reaches neither the plan nor the
    # comparison, so a slider left on screen stated a span nothing used. The R
    # twin's app hides its slider the same way.
    _, elements = _build_page(monkeypatch)
    partition = next(e for e in _of_type(elements, "Switch")
                     if e.text == "Partition by year (recommended)")
    years = _of_type(elements, "Range")[0]
    caption = next(e for e in _of_type(elements, "Label") if e.text == "Years")
    assert years.visible and caption.visible
    partition.value = False
    assert not years.visible and not caption.visible
    partition.value = True
    assert years.visible and caption.visible


def test_the_field_selector_can_leave_the_query_untagged(monkeypatch):
    # SearchPlan, scopus_count and compare_topics take field=None, and the R
    # twin's app offers "(none)", but every entry here wrapped the query in a
    # tag, so a query tagged by hand could not be sent from the app.
    _, elements = _build_page(monkeypatch)
    field = next(e for e in _of_type(elements, "Select")
                 if e._props.get("label") == "Search in")
    code = _of_type(elements, "Code")[0]
    labels = [option["label"] for option in field._props["options"]]
    assert labels[-1] == "(none)"
    assert "field='TITLE-ABS-KEY'" in code.content
    field.value = ""
    assert "field=" not in code.content


def test_the_app_declares_colours_its_text_can_be_read_on(monkeypatch):
    # NiceGUI's own primary, #5898d4, carries white text at 3.06:1 and stands on
    # white at the same ratio, under the 4.5:1 text needs, and every button
    # here is drawn in it.
    pytest.importorskip("nicegui")
    from nicegui import ui

    declared = {}
    colours = ui.colors

    def record(**kwargs):
        declared.update(kwargs)
        return colours(**kwargs)

    monkeypatch.setattr(ui, "colors", record)
    _build_page(monkeypatch)
    assert _contrast(declared["primary"], "#FFFFFF") >= 4.5


def test_a_figure_name_survives_a_quotation_mark_in_the_terms():
    # The comparison figure is named after the terms in play, and NiceGUI reads
    # props from a string, so a quotation mark would otherwise end the name.
    pytest.importorskip("nicegui")
    from nicegui.props import Props

    from scopusflow.app import _figure_props

    parsed = Props.parse(_figure_props('Share held by "deep" learning, by year'))
    assert parsed["role"] == "img"
    assert parsed["aria-label"] == "Share held by deep learning, by year"


def test_the_figures_are_named_and_the_sections_are_headings(monkeypatch):
    # A NiceGUI figure is a div holding matplotlib's SVG, with no title and no
    # name, so a screen reader read its tick labels or nothing. The page had no
    # top-level heading and its two section titles were plain labels.
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
        assert str(label._props["aria-level"]) == "2"
    _of_type(elements, "Range")[0].value = {"min": 2019, "max": 2019}
    buttons = {e.text: e for e in _of_type(elements, "Button") if e.text}

    async def run_both():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        _click(buttons["Fetch records"])
        await asyncio.sleep(1.0)
        _click(buttons["Compare topics"])
        await asyncio.sleep(1.0)
        return [e for i, e in client.elements.items() if i not in built]

    figures = _of_type(asyncio.run(run_both()), "Pyplot")
    assert all(f._props.get("role") == "img" for f in figures)
    assert [f._props.get("aria-label") for f in figures] == [
        "Records retrieved per year",
        "The most frequent sources, by records retrieved",
        "Share of the reference topic's records held by machine learning, "
        "deep learning, by year",
    ]


def test_the_page_shows_no_job_before_one_runs(monkeypatch):
    # The harvest's bar sat at zero before anything had run, which reads as a
    # stalled job, while the comparison's stayed hidden until used; and the
    # results area was blank with nothing said. The R twin's app shows neither
    # bar before a job and says where the records will appear.
    _, elements = _build_page(monkeypatch)
    assert not any(bar.visible for bar in _of_type(elements, "LinearProgress"))
    assert any(e.text == "Fetch records to see them here."
               for e in _of_type(elements, "Label"))
