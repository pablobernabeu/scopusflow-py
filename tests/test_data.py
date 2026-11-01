"""Offline tests for the bundled worked-example harvest."""

from pathlib import Path

import pandas as pd
import pytest

import scopusflow as sf
import scopusflow.data
from scopusflow.records import RECORD_COLUMNS

ROOT = Path(__file__).resolve().parents[1]


def test_example_records_has_the_documented_size_and_span():
    records = sf.example_records()
    assert len(records) == 138
    assert int(records["year"].min()) == 2015
    assert int(records["year"].max()) == 2024
    # The harvest is complete rather than sampled, so the rows per year are the
    # publications per year and the guides quote them as such.
    per_year = records["year"].value_counts().sort_index().tolist()
    assert per_year == [15, 9, 10, 15, 19, 13, 13, 15, 15, 14]


def test_example_records_matches_the_stable_schema():
    records = sf.example_records()
    assert list(records.columns) == list(RECORD_COLUMNS)
    assert pd.api.types.is_integer_dtype(records["year"])
    assert pd.api.types.is_integer_dtype(records["citations"])
    assert pd.api.types.is_integer_dtype(records["entry_number"])
    assert records["entry_number"].tolist() == list(range(1, len(records) + 1))


def test_example_records_returns_an_independent_copy():
    first = sf.example_records()
    first.loc[0, "title"] = "edited in place"
    second = sf.example_records()
    assert len(second) == 138
    assert second.loc[0, "title"] != "edited in place"


def test_example_records_keeps_the_gaps_a_real_harvest_has():
    records = sf.example_records()
    # No Scopus identifiers, these records not having come from Scopus, so
    # anything keyed on the identifier has to fall back to the DOI.
    assert records["scopus_id"].isna().all()
    assert records["doi"].isna().sum() == 11
    assert records["publication"].isna().sum() == 2
    assert records["title"].notna().all()


def test_example_records_stores_the_hyphen_as_the_r_twins_corpus_does():
    # The shared CSV is OpenAlex's text, in which five author names spell their
    # hyphen as U+2010. The R twin's build writes each as the ASCII hyphen, so
    # those names differed between the two corpora the docstrings call identical.
    records = sf.example_records()
    for column in ("doi", "title", "authors", "date", "publication", "query"):
        assert not any("\u2010" in value for value in records[column].dropna()), column
    assert {"Chih-Tao Chien", "Zhong-Shuai Wu", "Maher F. El-Kady", "Xiu-Yan Fu",
            "Woo-Jae Lee"} <= set(records["authors"].dropna())


def test_example_records_drops_the_missing_dois_rather_than_carrying_them():
    # A nullable string column yields pd.NA, whose str() is the literal "<NA>";
    # extract_dois must not pass that through as though it were a DOI.
    dois = sf.extract_dois(sf.example_records())
    assert len(dois) == 127
    assert "<NA>" not in dois
    assert all(d.startswith("10.") for d in dois)


# The bundled records came from OpenAlex's exact-phrase search for "graphene
# supercapacitor" in titles and abstracts, limited to journal articles. Scopus
# joins the words of an unquoted phrase with AND, so the unquoted search the
# guides gave as the corpus's own matches far more, about a hundred times as
# many records in OpenAlex. A methods paragraph built on it described a search
# that never ran.


def _page(*parts):
    path = ROOT.joinpath(*parts)
    if not path.exists():
        pytest.skip("the documentation is not part of an installed distribution")
    # White space is folded, so a sentence wrapped across lines still matches.
    return " ".join(path.read_text(encoding="utf-8").split())


def _folded(text):
    return " ".join(text.split())


def test_no_page_presents_the_unquoted_phrase_as_the_corpus_search():
    pages = {
        name: _page("docs", "guides", name)
        for name in ("getting-started.md", "plans-and-quota.md",
                     "analysing-a-literature.md")
    }
    pages["scopusflow.data"] = _folded(scopusflow.data.__doc__)
    claims = [
        "describes the search that produced the bundled corpus",
        "the bundled equivalent",
        "Run the query above against Scopus",
        "the equivalent query",
        "The live call that would produce `records` for real",
        "these counts are the publications the query matched",
    ]
    assert [(name, claim) for name, text in pages.items()
            for claim in claims if claim in text] == []
    for name, text in pages.items():
        assert "OpenAlex's exact-phrase search" in text, name


def test_the_demonstration_searches_quote_the_phrase():
    # Quoted, the phrase is searched as the corpus searched it. The data module
    # names that query, where it used to point at "the equivalent query".
    assert "sf.SearchPlan('\"graphene supercapacitor\"'" in _page(
        "docs", "guides", "plans-and-quota.md")
    assert "sf.scopus_query('\"graphene supercapacitor\"'" in _page(
        "docs", "guides", "analysing-a-literature.md")
    assert "sf.SearchPlan('\"graphene supercapacitor\"'" in _folded(
        sf.scopus_search_report.__doc__)
    assert 'TITLE-ABS-KEY("graphene supercapacitor")' in _folded(scopusflow.data.__doc__)
    # The live harvest the tracking guide sets against the bundled baseline
    # quotes it too, and is diffed against a harvest of the reader's own.
    tracking = _page("docs", "guides", "tracking-literature-change.md")
    assert "sf.scopus_query('\"graphene supercapacitor\"'" in tracking
    assert "the bundled corpus came from OpenAlex" in tracking


def test_the_search_record_demonstrations_say_no_search_was_run():
    # The attributes set by hand, the reported totals among them, are the
    # corpus's own counts and describe no Scopus search.
    plans = _page("docs", "guides", "plans-and-quota.md")
    assert "describes no search that was run" in plans
    assert "illustrative" in plans
    doc = _folded(sf.scopus_search_report.__doc__)
    assert "describes no search that was run" in doc
    assert "illustrative" in doc
