"""Offline tests for the bundled worked-example harvest."""

import pandas as pd

import scopusflow as sf
from scopusflow.records import RECORD_COLUMNS


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
    first.drop(index=first.index[1:], inplace=True)
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


def test_example_records_drops_the_missing_dois_rather_than_carrying_them():
    # A nullable string column yields pd.NA, whose str() is the literal "<NA>";
    # extract_dois must not pass that through as though it were a DOI.
    dois = sf.extract_dois(sf.example_records())
    assert len(dois) == 127
    assert "<NA>" not in dois
    assert all(d.startswith("10.") for d in dois)
