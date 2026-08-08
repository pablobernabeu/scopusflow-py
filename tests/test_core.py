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


def test_diff_and_extract_dois():
    assert sf.extract_dois(["https://doi.org/10.1/A", "DOI: 10.1/a"]) == ["10.1/A"]
    d = sf.diff_dois(old=["10.1/a", "10.1/b"], new=["10.1/b", "10.1/c"])
    status = dict(zip(d["doi"], d["status"], strict=True))
    assert status["10.1/c"] == "added"
    assert status["10.1/a"] == "removed"
    assert status["10.1/b"] == "unchanged"
