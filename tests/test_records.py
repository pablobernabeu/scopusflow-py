"""Offline tests for to_records() normalisation, including authkeywords."""

import pandas as pd
import pytest

from scopusflow.records import RECORD_COLUMNS, to_records


def test_to_records_matches_the_stable_schema():
    results = [{
        "eid": "2-s2.0-85000000001",
        "doi": "10.1/a",
        "title": "A study",
        "author_names": "Smith J.",
        "coverDate": "2020-05-01",
        "publicationName": "Journal",
        "citedby_count": "3",
    }]
    out = to_records(results, query="TITLE(x)")
    assert list(out.columns) == RECORD_COLUMNS
    assert out.loc[0, "doi"] == "10.1/a"
    assert out.loc[0, "year"] == 2020


def test_view_none_and_standard_never_carry_authkeywords():
    results = [{"doi": "10.1/x", "authkeywords": "graphene | supercapacitor"}]
    default = to_records(results)
    standard = to_records(results, view="STANDARD")
    assert "authkeywords" not in default.columns
    assert "authkeywords" not in standard.columns
    assert list(default.columns) == RECORD_COLUMNS


def test_complete_view_adds_a_populated_authkeywords_column():
    results = [{"doi": "10.1/x", "authkeywords": "graphene | supercapacitor | energy storage"}]
    out = to_records(results, view="COMPLETE")
    assert "authkeywords" in out.columns
    assert out.loc[0, "authkeywords"] == "graphene | supercapacitor | energy storage"


def test_complete_view_adds_an_na_authkeywords_column_when_the_api_omits_it():
    # Reflects a real, observed case: a key entitled for COMPLETE view whose
    # author-keyword field still comes back empty for every document.
    results = [{"doi": "10.1/x"}]
    out = to_records(results, view="COMPLETE")
    assert "authkeywords" in out.columns
    assert pd.isna(out.loc[0, "authkeywords"])


def test_an_empty_result_under_complete_view_still_types_the_authkeywords_column():
    out = to_records([], view="COMPLETE")
    assert len(out) == 0
    assert "authkeywords" in out.columns


@pytest.mark.parametrize("eid", [None, float("nan"), pd.NA])
def test_a_missing_eid_yields_na_not_the_string_nan(eid):
    # bool(float("nan")) is True, so a truthiness test used to stringify a
    # missing identifier into the literal "nan", which every downstream guard
    # then accepts as a real Scopus ID.
    out = to_records([{"eid": eid, "doi": "10.1/x"}])
    assert pd.isna(out.loc[0, "scopus_id"])


@pytest.mark.parametrize("cited", [None, "", float("nan"), pd.NA])
def test_a_missing_citation_count_yields_na_rather_than_raising(cited):
    out = to_records([{"eid": "2-s2.0-1", "citedby_count": cited}])
    assert pd.isna(out.loc[0, "citations"])


def test_a_zero_citation_count_is_kept_rather_than_read_as_missing():
    out = to_records([{"eid": "2-s2.0-1", "citedby_count": "0"}])
    assert out.loc[0, "citations"] == 0
    assert not pd.isna(out.loc[0, "citations"])
