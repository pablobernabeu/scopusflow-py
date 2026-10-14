"""Offline tests for comparing two retrievals, by DOI and record by record."""

from pathlib import Path

import pandas as pd
import pytest

import scopusflow as sf


def diff_fixture():
    """Two pulls of one search. Rows 1 to 7 are the earlier pull and rows 8 to
    15 the later one. Their records carry Scopus identifiers, which the bundled
    corpus lacks, alongside records from another source that carry none, DOIs
    spelled as other sources spell them, a record re-indexed under a new
    identifier and records with neither key. The file is byte-identical to the
    R twin's tests/testthat/fixtures/diff-fixture.csv, whose suite asserts the
    same results."""
    records = sf.read_records(Path(__file__).parent / "fixtures" / "diff-fixture.csv")
    return records.iloc[:7], records.iloc[7:]


def values(column):
    """A column as plain Python values, with None for every missing value, so
    that a comparison does not depend on the dtype pandas chose."""
    return [None if pd.isna(v) else v for v in column.astype(object)]


def test_the_diff_counts_the_records_it_could_not_compare_for_want_of_a_doi():
    # The records without a DOI used to vanish from the diff without a count.
    # The R suite asserts the same rows and counts on the same fixture.
    old, new = diff_fixture()
    d = sf.diff_dois(old=old, new=new)
    assert list(d["doi"]) == [
        "10.5555/new.8", "10.5555/new.9", "10.5555/gone.2",
        "10.5555/JOINED.5", "10.5555/SIX.6", "10.5555/kept.1", "10.5555/moved",
    ]
    assert list(d["status"]) == ["added"] * 2 + ["removed"] + ["unchanged"] * 4
    assert d.attrs["n_old_without_doi"] == 2
    assert d.attrs["n_new_without_doi"] == 2
    assert type(d.attrs["n_old_without_doi"]) is int


def test_the_diff_counts_missing_and_blank_dois_in_lists_too():
    d = sf.diff_dois(old=["10.1/a", None], new=["10.1/a", ""])
    assert (d.attrs["n_old_without_doi"], d.attrs["n_new_without_doi"]) == (1, 1)
    complete = sf.diff_dois(old=["10.1/a"], new=["10.1/a"])
    assert (complete.attrs["n_old_without_doi"], complete.attrs["n_new_without_doi"]) == (0, 0)


def test_the_record_diff_matches_on_identifiers_and_failing_them_on_dois():
    # The R suite asserts the same rows, values and counts on the same fixture.
    # The record re-indexed under a new identifier is a conflict on both
    # sides, the record without a DOI is matched on its identifier, and the
    # records without an identifier join the identified records carrying their
    # DOIs, however the DOIs are spelled.
    old, new = diff_fixture()
    d = sf.diff_records(old, new)
    assert list(d.columns) == ["status", "scopus_id", "doi", "title", "year",
                               "citations_old", "citations_new"]
    assert list(d["status"]) == (["added"] * 2 + ["removed"] + ["conflict"] * 2
                                 + ["unchanged"] * 4)
    assert values(d["scopus_id"]) == [
        "85000000008", None, "85000000002", "85000000003", "85000000033",
        "85000000005", "85000000006", "85000000001", "85000000004",
    ]
    assert values(d["doi"]) == [
        "10.5555/new.8", "10.5555/new.9", "10.5555/gone.2", "10.5555/MOVED",
        "10.5555/moved", "10.5555/JOINED.5", "10.5555/SIX.6", "10.5555/kept.1", None,
    ]
    assert values(d["title"])[1] == "A new record from another source"
    assert values(d["title"])[6] == "A record the later pull holds without an identifier"
    assert values(d["year"]) == [2022, 2022, 2020, 2021, 2021, 2021, 2019, 2020, 2021]
    assert values(d["citations_old"]) == [None, None, 3, 8, None, 2, 7, 5, 1]
    assert values(d["citations_new"]) == [0, None, None, None, 10, 6, 11, 9, 4]
    assert d.attrs["n_old_without_id_or_doi"] == 1
    assert d.attrs["n_new_without_id_or_doi"] == 1


def test_a_record_is_in_conflict_only_where_the_other_pull_gives_its_doi_to_another():
    # Two distinct records sharing a DOI in both pulls are each matched on
    # their identifier and unchanged. A third record under that DOI, new to the
    # later pull, may be either of them re-indexed or a third paper.
    old = pd.DataFrame({"scopus_id": ["1", "2"], "doi": ["10.5555/x", "10.5555/X"]})
    new = pd.DataFrame({"scopus_id": ["1", "2", "3"],
                        "doi": ["10.5555/x", "10.5555/X", "10.5555/x"]})
    d = sf.diff_records(old, new)
    assert list(d["status"]) == ["conflict", "unchanged", "unchanged"]
    assert values(d["scopus_id"]) == ["3", "2", "1"]

    # A record without an identifier whose DOI two identified records carry
    # cannot be assigned to either, so all three are in conflict.
    unassigned = sf.diff_records(
        pd.DataFrame({"scopus_id": ["1", "2"], "doi": ["10.5555/x", "10.5555/x"]}),
        pd.DataFrame({"scopus_id": [None], "doi": ["10.5555/x"]}),
    )
    assert list(unassigned["status"]) == ["conflict"] * 3

    # Records that share a DOI within one pull alone are not in conflict.
    added = sf.diff_records(
        pd.DataFrame({"scopus_id": ["1"], "doi": ["10.5555/a"]}),
        pd.DataFrame({"scopus_id": ["1", "2", "3"],
                      "doi": ["10.5555/a", "10.5555/b", "10.5555/b"]}),
    )
    assert list(added["status"]) == ["added", "added", "unchanged"]


def test_the_record_diff_gives_the_bundled_corpus_the_doi_diffs_counts():
    # The corpus carries no identifiers, so every record is matched on its DOI
    # and those without one cannot be compared. The tracking guide's baseline
    # ends in 2021, and its counts are the ones it quotes.
    records = sf.example_records()
    baseline = records[(records["year"] <= 2021).fillna(False)]
    later = records.iloc[1:]
    d = sf.diff_records(baseline, later)
    assert d["status"].value_counts().to_dict() == {
        "added": 43, "removed": 1, "unchanged": 83}
    assert d.attrs["n_old_without_id_or_doi"] == 10
    assert d.attrs["n_new_without_id_or_doi"] == 11
    removed = d[d["status"] == "removed"]
    assert values(removed["doi"]) == [records["doi"].iloc[0]]
    assert values(removed["citations_old"]) == [records["citations"].iloc[0]]

    dois = sf.diff_dois(old=baseline, new=later)
    assert dois["status"].value_counts().to_dict() == {
        "added": 43, "removed": 1, "unchanged": 83}
    assert (dois.attrs["n_old_without_doi"], dois.attrs["n_new_without_doi"]) == (10, 11)
    # The guide's record counts: 44 records new since the baseline, 43 of them
    # with a DOI, and 93 in both pulls, 83 of them with a DOI.
    assert int((later["year"] > 2021).sum()) == 44
    assert len(baseline) - 1 == 93


def test_the_record_diff_handles_empty_pulls_and_refuses_anything_but_records():
    empty = sf.example_records().iloc[:0]
    d = sf.diff_records(empty, empty)
    assert len(d) == 0
    assert d.attrs["n_old_without_id_or_doi"] == 0
    assert list(d.columns) == ["status", "scopus_id", "doi", "title", "year",
                               "citations_old", "citations_new"]
    added = sf.diff_records(empty, sf.example_records().iloc[[0, 2]])
    assert list(added["status"]) == ["added", "added"]

    with pytest.raises(ValueError, match="old must be a record frame"):
        sf.diff_records(["10.1/a"], empty)
    with pytest.raises(ValueError, match="new must have a scopus_id or a doi column"):
        sf.diff_records(empty, pd.DataFrame({"title": ["x"]}))
