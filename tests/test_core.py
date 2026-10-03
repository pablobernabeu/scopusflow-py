"""Offline tests for the pure-logic layer (no API key, no pybliometrics)."""

import pandas as pd
import pytest

import scopusflow as sf


def test_every_name_the_api_page_lists_is_importable_from_the_package():
    # docs/api.md states the rule; COMPARISON_COLUMNS quietly broke it, and the
    # page's own example had to reach it through sf.compare to work around that.
    import re
    from pathlib import Path

    page = Path(__file__).resolve().parents[1] / "docs" / "api.md"
    if not page.exists():
        pytest.skip("the documentation is not part of an installed distribution")
    listed = re.findall(r"^:::\s+scopusflow\.(\S+)", page.read_text(encoding="utf-8"), re.M)
    assert listed, "the API page should list some names"
    assert [n for n in listed if not hasattr(sf, n.rsplit(".", 1)[-1])] == []
    for constant in ("RECORD_COLUMNS", "TREND_COLUMNS", "COMPARISON_COLUMNS",
                     "ABSTRACT_COLUMNS"):
        assert constant in sf.__all__


def test_scopus_query_builds_field_tagged_boolean():
    assert sf.scopus_query("a", "b", field="TITLE-ABS-KEY") == (
        "TITLE-ABS-KEY(a) AND TITLE-ABS-KEY(b)"
    )
    assert sf.scopus_query("CRISPR", "Cas9", op="OR") == "CRISPR OR Cas9"
    with pytest.raises(ValueError):
        sf.scopus_query("a", "")
    with pytest.raises(ValueError):
        sf.scopus_query("a", op="XOR")


def _grouping_fixture() -> dict:
    # The same file sits in the R suite, byte for byte, so both twins are held
    # to one set of expected strings.
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent / "fixtures" / "query-grouping.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_query(case: dict) -> str:
    # A term written as an object stands for the scopus_query() call that
    # produces it, which is how the fixture spells a nested composition.
    terms = [t if isinstance(t, str) else _fixture_query(t) for t in case["terms"]]
    return sf.scopus_query(*terms, op=case["op"], field=case["field"])


@pytest.mark.parametrize(
    "case", _grouping_fixture()["scopus_query"], ids=lambda case: case["id"]
)
def test_scopus_query_matches_the_shared_grouping_fixture(case):
    # Scopus joins the words of an unquoted term with AND, so a bare join of
    # multi-word terms regrouped them: "machine learning OR deep learning" read
    # as machine AND (learning OR deep) AND learning.
    assert _fixture_query(case) == case["expected"]


def test_scopus_query_rejects_a_term_of_white_space_alone():
    # str.strip() removes a no-break space, so the term is empty. The R twin
    # trims the same characters and refuses the same input.
    with pytest.raises(ValueError):
        sf.scopus_query("\N{NO-BREAK SPACE}", "b")


@pytest.mark.parametrize(
    "case", _grouping_fixture()["needs_group"], ids=lambda case: case["expr"]
)
def test_the_year_fold_scan_finds_only_top_level_operators(case):
    from scopusflow.query import _needs_group

    assert _needs_group(case["expr"]) is case["needs_group"]


def test_and_clause_brackets_only_a_query_that_needs_it():
    from scopusflow.query import _and_clause

    assert _and_clause("TITLE(a) AND NOT TITLE(b)", "PUBYEAR IS 2015") == (
        "(TITLE(a) AND NOT TITLE(b)) AND PUBYEAR IS 2015"
    )
    # Operator-free strings are sent exactly as before, so their checkpoints
    # and pybliometrics' download cache, keyed on the query, stay valid.
    assert _and_clause("TITLE(a) AND TITLE(b)", "PUBYEAR IS 2015") == (
        "TITLE(a) AND TITLE(b) AND PUBYEAR IS 2015"
    )


def _checks_fixture() -> dict:
    # Shared byte for byte with the R suite, so both twins report the same
    # problems in the same words.
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent / "fixtures" / "query-checks.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _checks_fixture()["cases"], ids=lambda case: case["id"])
def test_the_query_scanner_matches_the_shared_fixture(case):
    from scopusflow.query import _query_problems

    messages = _checks_fixture()["messages"]
    problems = _query_problems(case["query"], case["field"])
    assert [p.code for p in problems] == case["problems"]
    assert [p.message for p in problems] == [messages[c] for c in case["problems"]]


@pytest.mark.parametrize("case", _checks_fixture()["cases"], ids=lambda case: case["id"])
def test_check_query_raises_the_first_error_and_otherwise_warns(case):
    import warnings

    from scopusflow.query import _check_query

    messages = _checks_fixture()["messages"]
    errors = [c for c in case["problems"] if c != "indexterms"]
    if errors:
        with pytest.raises(ValueError) as caught:
            _check_query(case["query"], case["field"])
        assert str(caught.value) == messages[errors[0]]
    elif case["problems"]:
        from scopusflow.query import QuerySyntaxWarning

        with pytest.warns(QuerySyntaxWarning) as caught:
            _check_query(case["query"], case["field"])
        assert [str(w.message) for w in caught] == [messages["indexterms"]]
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _check_query(case["query"], case["field"])


def _refuse_every_search(monkeypatch):
    # A stand-in for pybliometrics that fails the test if any search is made.
    class _NoSearch:
        def __init__(self, query, **kwargs):
            raise AssertionError(f"a request was made for {query!r}")

    _use_search(monkeypatch, _NoSearch)


def test_a_query_the_api_cannot_run_as_written_is_refused_before_any_request(monkeypatch):
    from scopusflow.intersections import scopus_intersections

    _refuse_every_search(monkeypatch)
    # Pasted from the web interface's refinement panel, which the Search API
    # ignores, so the search would run unfiltered.
    refined = 'x AND (LIMIT-TO (DOCTYPE, "ar"))'
    for call in (
        lambda: sf.SearchPlan(refined),
        lambda: sf.scopus_count(refined),
        lambda: sf.scopus_trend(refined, years=[2020]),
        lambda: sf.compare_topics(refined, ["y"], years=[2020]),
        lambda: sf.compare_topics("x", [refined], years=[2020]),
        lambda: scopus_intersections({"a": "x", "b": refined}),
        # A tagged query wrapped in another tag, which the API rejects with
        # HTTP 400.
        lambda: sf.SearchPlan("TITLE(x)", field="TITLE-ABS-KEY"),
        lambda: sf.scopus_count("TITLE(x)", field="title-abs-key"),
        lambda: sf.compare_topics("x", ["y", "TITLE(z)"], years=[2020], field="ABS"),
        lambda: sf.SearchPlan("(a OR b", field="TITLE"),
    ):
        # The refusal is the offline check's own, not some other ValueError.
        with pytest.raises(ValueError) as caught:
            call()
        assert str(caught.value) in _checks_fixture()["messages"].values()


def test_a_tagged_concept_is_checked_as_written_without_the_field():
    from scopusflow.intersections import _intersection_rows

    rows = _intersection_rows(
        {"a": "graphene", "b": 'TITLE-ABS-KEY ( "working memory" )'},
        None, None, " × ", "TITLE-ABS-KEY",
    )
    assert list(rows["query"]) == [
        "TITLE-ABS-KEY(graphene)", 'TITLE-ABS-KEY ( "working memory" )',
    ]


def test_indexterms_warns_and_the_plan_is_still_built():
    from scopusflow.query import QuerySyntaxWarning

    with pytest.warns(QuerySyntaxWarning, match="INDEXTERMS"):
        plan = sf.SearchPlan("INDEXTERMS(memory)")
    assert plan.wrapped_query == "INDEXTERMS(memory)"
    # The changelog promises a UserWarning, so ordinary filters still apply.
    assert issubclass(QuerySyntaxWarning, UserWarning)


def test_wrap_field_refuses_to_wrap_a_tagged_query():
    with pytest.raises(ValueError, match="already opens with a field tag"):
        sf.wrap_field("TITLE(x)", "TITLE-ABS-KEY")
    with pytest.raises(ValueError, match="already opens with a field tag"):
        sf.scopus_query("TITLE(x)", "y", field="TITLE-ABS-KEY")
    assert sf.scopus_query("TITLE(x)", "y") == "TITLE(x) AND y"


def test_a_plan_normalises_its_field_tag_as_the_r_twin_does():
    canonical = sf.SearchPlan("x", field="TITLE-ABS-KEY")
    loose = sf.SearchPlan("x", field=" title-abs-key ")
    assert loose.field == "TITLE-ABS-KEY"
    assert loose == canonical
    assert sf.SearchPlan("x").field is None
    # The search record printed ' title-abs-key ' and its reproduction snippet
    # rebuilt a plan unequal to the one it came from.
    assert 'field="TITLE-ABS-KEY",' in sf.scopus_search_report(loose).snippet


@pytest.mark.parametrize("bad", ["TITLE ABS", "", "   ", 123, True, ["TITLE"]])
def test_a_plan_refuses_an_invalid_field_tag_at_construction(bad):
    with pytest.raises(ValueError, match="field must be None or a Scopus field tag"):
        sf.SearchPlan("x", field=bad)


def test_plan_partitions_by_year():
    plan = sf.SearchPlan("x", years=[2020, 2018, 2018], field="TITLE", partition="year")
    cells = plan.cells()
    assert [c.year for c in cells] == [2018, 2020]
    assert cells[0].query == "TITLE(x)"
    # A single cell carries a date range.
    single = sf.SearchPlan("x", years=range(2015, 2021)).cells()
    assert single[0].date == "2015-2020"
    with pytest.raises(ValueError):
        sf.SearchPlan("x", partition="year")


@pytest.mark.parametrize("bad", [[2015.7], [1500], [2500], ["2015"], [pd.NA], [None]])
def test_every_entry_point_refuses_the_years_the_r_twin_refuses(bad):
    # One validator behind every entry point, mirroring the R twin's
    # scopus_check_years(), so the two engines cannot disagree about what a
    # year is. Each of these used to be truncated, or sent to the API as given.
    from scopusflow.count import _count_query
    from scopusflow.intersections import scopus_intersections

    with pytest.raises(ValueError, match="whole numbers"):
        sf.SearchPlan("x", years=bad)
    with pytest.raises(ValueError, match="whole numbers"):
        _count_query("x", years=bad)
    with pytest.raises(ValueError, match="whole numbers"):
        sf.scopus_trend("x", years=bad)
    with pytest.raises(ValueError, match="whole numbers"):
        sf.compare_topics("ref", ["t"], years=bad)
    with pytest.raises(ValueError, match="whole numbers"):
        scopus_intersections({"a": "x"}, years=bad)


def _use_search(monkeypatch, search_class):
    import sys
    import types

    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.ScopusSearch = search_class
    pkg = types.ModuleType("pybliometrics")
    pkg.scopus = scopus
    monkeypatch.setitem(sys.modules, "pybliometrics", pkg)
    monkeypatch.setitem(sys.modules, "pybliometrics.scopus", scopus)


def test_scopus_count_is_sent_with_refresh_unless_the_caller_sends_it(monkeypatch):
    # pybliometrics answers a query an earlier harvest filed with the number
    # of rows it cached, unless refresh is True.
    sent = []

    class _Search:
        def __init__(self, query, **kwargs):
            sent.append(kwargs.get("refresh", "not sent"))

        def get_results_size(self):
            return 7

    _use_search(monkeypatch, _Search)
    assert sf.scopus_count("graphene", years=[2020]) == 7
    assert sf.scopus_count("graphene", refresh=False) == 7
    assert sent == [True, False]


def test_a_count_from_pybliometrics_cache_is_warned_about(monkeypatch):
    import time
    from datetime import datetime, timezone

    written = datetime(2026, 7, 1, 9, 30, 15, tzinfo=timezone.utc)

    class _Cached:
        def __init__(self, query, **kwargs):
            pass

        def get_results_size(self):
            return 2

        def get_cache_file_mdate(self):
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(written.timestamp()))

        def get_key_remaining_quota(self):
            return None

    _use_search(monkeypatch, _Cached)
    with pytest.warns(UserWarning, match="pybliometrics' own cache") as caught:
        assert sf.scopus_count("graphene", years=[2020], refresh=False) == 2
    message = str(caught[0].message)
    assert "'graphene AND PUBYEAR IS 2020'" in message
    assert "2026-07-01 09:30:15 UTC" in message


def test_a_count_whose_cache_time_cannot_be_read_is_still_warned_about(monkeypatch):
    # No response headers mark the count as read from the cache, and an
    # unreadable file time must not let it pass for the API's total.
    class _Unreadable:
        def __init__(self, query, **kwargs):
            pass

        def get_results_size(self):
            return 2

        def get_cache_file_mdate(self):
            return "yesterday"

        def get_key_remaining_quota(self):
            return None

    _use_search(monkeypatch, _Unreadable)
    with pytest.warns(UserWarning, match="time could not be read") as caught:
        assert sf.scopus_count("graphene", refresh=False) == 2
    assert "not the API's total" in str(caught[0].message)


def test_a_plan_normalises_its_years_to_whole_integers():
    # cells() renders the year into the cell's date, and str(2015.0) would
    # reach the API as "2015.0".
    plan = sf.SearchPlan("x", years=range(2015, 2018))
    assert plan.years == (2015, 2016, 2017)
    assert plan.cells()[0].date == "2015-2017"
    assert sf.SearchPlan("x", years=[2019.0]).cells()[0].date == "2019"


def test_to_records_normalises_to_the_stable_schema():
    results = [
        {
            "eid": "2-s2.0-85000000001",
            "doi": "10.1/a",
            "title": "A study",
            "author_names": "Smith J.;Doe A.",
            "coverDate": "2020-05-01",
            "publicationName": "Journal",
            "citedby_count": "7",
        }
    ]
    df = sf.to_records(results, query="q")
    assert list(df.columns) == sf.RECORD_COLUMNS
    assert df.loc[0, "scopus_id"] == "85000000001"
    assert df.loc[0, "year"] == 2020
    assert df.loc[0, "citations"] == 7


def test_top_counts_sources_and_splits_authors():
    df = pd.DataFrame(
        {"publication": ["Nature", "Nature", "Cell"], "authors": ["A;B", "A", "C"]},
    )
    top_src = sf.top(df, by="source")
    assert top_src.iloc[0]["value"] == "Nature"
    assert top_src.iloc[0]["n"] == 2
    top_auth = sf.top(df, by="author")
    assert int(top_auth.set_index("value").loc["A", "n"]) == 2


def test_top_accepts_an_n_beyond_32_bit_range():
    # The R twin's scopus_top() used to coerce n to a 32-bit integer before
    # trimming, so anything past 2**31 became NA and raised. Pin the shared
    # answer here as well, so the two halves keep agreeing at every n.
    df = pd.DataFrame(
        {"publication": ["Nature", "Nature", "Cell"], "authors": ["A;B", "A", "C"]},
    )
    every_source = sf.top(df, by="source", n=1000)
    assert len(every_source) == 2
    assert sf.top(df, by="source", n=10**10).equals(every_source)
    assert sf.top(df, by="source", n=2**40).equals(every_source)


def test_diff_and_extract_dois():
    assert sf.extract_dois(["https://doi.org/10.1/A", "DOI: 10.1/a"]) == ["10.1/A"]
    d = sf.diff_dois(old=["10.1/a", "10.1/b"], new=["10.1/b", "10.1/c"])
    status = dict(zip(d["doi"], d["status"], strict=True))
    assert status["10.1/c"] == "added"
    assert status["10.1/a"] == "removed"
    assert status["10.1/b"] == "unchanged"
