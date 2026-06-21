"""Offline tests for the GUI's pure helpers (no NiceGUI, no network)."""

import ast

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


def test_app_parse_progress_reads_latest_valid_marker():
    lines = ["Cell 1/8: fetching x (2018)", "Cell 2/8: fetching x (2019)"]
    assert app_parse_progress(lines) == {"done": 2, "total": 8}
    assert app_parse_progress([]) is None
    assert app_parse_progress(["no marker"]) is None
    # A "k/N" without the trailing colon (e.g. echoed in a query) is ignored.
    assert app_parse_progress(["fetching 'Cell 9/9 study'"]) is None
    # done > total is rejected.
    assert app_parse_progress(["Cell 9/2: bogus"]) is None
