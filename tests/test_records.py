"""Offline tests for to_records() normalisation, including authkeywords."""

import json
import warnings
from pathlib import Path

import pandas as pd
import pytest

import scopusflow.records as records_module
from scopusflow.records import RECORD_COLUMNS, to_records


def _complete_authors_fixture() -> dict:
    # The same file sits in the R suite, byte for byte, so both twins are held
    # to one authors string and one warning.
    path = Path(__file__).resolve().parent / "fixtures" / "complete-authors.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _extended_fixture() -> dict:
    # The same file sits in the R suite, byte for byte. The R twin parses the
    # raw entries, and this one reads the fields pybliometrics builds from them
    # (test_pyb.py holds those to the real parser).
    path = Path(__file__).resolve().parent / "fixtures" / "extended-entry.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_row(frame: pd.DataFrame, expected: dict) -> None:
    """``frame`` holds one row with the columns of ``expected``, in order, and
    its values, a JSON null standing for a missing value."""
    assert list(frame.columns) == list(expected)
    assert len(frame) == 1
    for column, want in expected.items():
        got = frame.iloc[0][column]
        if want is None:
            assert pd.isna(got), column
        else:
            assert got == want, column


def _complete_row(author_names: str | None) -> dict:
    """A COMPLETE-view row as pybliometrics hands it over for the fixture entry."""
    entry = _complete_authors_fixture()["entry"]
    return {"eid": entry["eid"], "doi": entry["prism:doi"], "title": entry["dc:title"],
            "creator": entry["dc:creator"], "author_names": author_names}


def test_complete_authors_are_joined_as_the_r_twin_joins_them():
    # pybliometrics joins author_names with a bare ';', which the R twin never
    # splits, so a list written here read there as one name.
    fixture = _complete_authors_fixture()
    out = to_records([_complete_row(fixture["author_names"])], view="COMPLETE")
    assert out.loc[0, "authors"] == fixture["expected_authors"]
    # A null or empty given name, which pybliometrics writes as the surname and
    # a bare comma, leaves the surname alone in both twins.
    blank = fixture["blank_given_names"]
    out = to_records([_complete_row(blank["author_names"])], view="COMPLETE")
    assert out.loc[0, "authors"] == blank["expected_authors"]


def test_a_standard_record_holds_its_first_author():
    # Without the COMPLETE view's author array pybliometrics builds no
    # author_names, and the column falls back to dc:creator, the first author.
    out = to_records([_complete_row(None)], view="STANDARD")
    assert out.loc[0, "authors"] == "Cong L."


@pytest.mark.parametrize(("joined", "expected"), [
    ("Cong, Le;Zhang, Feng", "Cong, Le; Zhang, Feng"),
    ("Cong, Le; Zhang, Feng", "Cong, Le; Zhang, Feng"),
    ("Cong, ;Zhang, Feng", "Cong; Zhang, Feng"),
    (" Cong, Le ;;Zhang, Feng; ", "Cong, Le; Zhang, Feng"),
    ("Cong L.", "Cong L."),
])
def test_join_authors_joins_pybliometrics_list_as_the_r_twin_does(joined, expected):
    # Joining again gives the same string, so a checkpoint written either way
    # can be passed through it on resume.
    assert records_module._join_authors(joined) == expected
    assert records_module._join_authors(expected) == expected


@pytest.mark.parametrize("missing", [None, "", " ; ", ",", float("nan"), pd.NA])
def test_join_authors_gives_none_when_nobody_is_named(missing):
    assert records_module._join_authors(missing) is None


def test_an_author_tally_of_a_standard_harvest_says_once_that_it_counts_first_authors(
    monkeypatch,
):
    monkeypatch.setattr(records_module, "_first_author_warned", False)
    standard = pd.DataFrame({"publication": ["Nature"], "authors": ["Cong L."]})
    standard.attrs["view"] = "STANDARD"
    with pytest.warns(UserWarning) as caught:
        records_module.top(standard, by="author")
    expected = _complete_authors_fixture()["first_author_warning"]
    assert [str(w.message) for w in caught] == [expected]
    # Once per process.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        records_module.top(standard, by="author")


def test_the_first_author_warning_is_reserved_for_author_tallies_of_standard_sets(
    monkeypatch,
):
    from scopusflow.export import to_bibtex, to_ris

    monkeypatch.setattr(records_module, "_first_author_warned", False)
    frame = pd.DataFrame({"publication": ["Nature"], "authors": ["Cong L."]})
    standard, complete = frame.copy(), frame.copy()
    standard.attrs["view"] = "STANDARD"
    complete.attrs["view"] = "COMPLETE"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        # A set that records no view, as the bundled harvest records none,
        # cannot be judged, and a COMPLETE set lists its authors.
        records_module.top(frame, by="author")
        records_module.top(complete, by="author")
        # A source tally and the reference-manager exports are not author tallies.
        records_module.top(standard, by="source")
        to_bibtex(standard)
        to_ris(standard)
    assert records_module._first_author_warned is False


def test_ris_gives_each_author_of_a_complete_record_a_line_of_its_own():
    from scopusflow.export import to_ris

    fixture = _complete_authors_fixture()
    ris = to_ris(to_records([_complete_row(fixture["author_names"])], view="COMPLETE"))
    assert "AU  - Cong, Le\nAU  - Zhang, Feng\nAU  - Doudna, Jennifer A.\n" in ris


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


@pytest.mark.parametrize("view", ["standard", "complete"])
def test_extended_fields_keep_what_both_views_send_and_the_complete_abstract(view):
    # The Search API sends these fields in every response, at no extra quota,
    # and the records discarded them. The R suite parses the raw entries of the
    # same fixture and must return the same rows.
    fixture = _extended_fixture()
    out = to_records([fixture["pybliometrics"][view]], query=fixture["query"],
                     view=view.upper(), fields="extended")
    _assert_row(out, fixture["expected"][view])


def test_the_core_fields_stay_the_default():
    fixture = _extended_fixture()
    complete = to_records([fixture["pybliometrics"]["complete"]], view="COMPLETE")
    assert list(complete.columns) == [*RECORD_COLUMNS, "authkeywords"]
    standard = to_records([fixture["pybliometrics"]["standard"]], view="STANDARD")
    assert list(standard.columns) == RECORD_COLUMNS


def test_extended_columns_are_exported_in_the_order_both_views_add_them():
    import scopusflow as sf

    expected = list(_extended_fixture()["expected"]["standard"])
    assert sf.EXTENDED_COLUMNS == expected[len(RECORD_COLUMNS):]
    assert "EXTENDED_COLUMNS" in sf.__all__


def test_an_empty_extended_result_carries_every_extended_column():
    fixture = _extended_fixture()
    assert list(to_records([], view="COMPLETE", fields="extended").columns) == list(
        fixture["expected"]["complete"])
    assert list(to_records([], fields="extended").columns) == list(
        fixture["expected"]["standard"])


def test_open_access_keeps_the_status_code_scopus_sends():
    # Elsevier's guide gives 0 for not open access, 1 for gold and 2 for green,
    # so the column holds a status code that can exceed 1. pybliometrics hands
    # it over as an int, and a dict may carry the API's text.
    out = to_records([{"doi": "10.5555/x", "openaccess": 2},
                      {"doi": "10.5555/y", "openaccess": "0"},
                      {"doi": "10.5555/z"}], fields="extended")
    assert out.loc[0, "open_access"] == 2
    assert out.loc[1, "open_access"] == 0
    assert pd.isna(out.loc[2, "open_access"])


def test_fields_must_be_core_or_extended():
    with pytest.raises(ValueError, match="fields must be 'core' or 'extended'"):
        to_records([], fields="all")


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
