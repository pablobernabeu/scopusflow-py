"""Offline tests for the GUI's pure helpers (no NiceGUI, no network)."""

import ast
import logging

import pandas as pd

from scopusflow.app_helpers import app_code_mirror, app_parse_progress, app_years_code


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
    # Terms but no year span -> skipped (compare_topics needs an explicit span).
    assert "compare_topics" not in app_code_mirror(
        query="x", years=None, partition="none", compare_terms=["a"])


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


def test_app_parse_progress_reads_latest_valid_marker():
    lines = ["Cell 1/8: fetching x (2018)", "Cell 2/8: fetching x (2019)"]
    assert app_parse_progress(lines) == {"done": 2, "total": 8}
    assert app_parse_progress([]) is None
    assert app_parse_progress(["no marker"]) is None
    # A "k/N" without the trailing colon (e.g. echoed in a query) is ignored.
    assert app_parse_progress(["fetching 'Cell 9/9 study'"]) is None
    # done > total is rejected.
    assert app_parse_progress(["Cell 9/2: bogus"]) is None
