"""Offline tests for the pure-logic layer (no API key, no pybliometrics)."""

import pandas as pd
import pytest

import scopusflow as sf


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
