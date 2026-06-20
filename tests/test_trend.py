"""Offline tests for the publication-trend layer (no API key, no pybliometrics)."""

import pandas as pd
import pytest

from scopusflow.trend import _trend_frame, scopus_trend, year_counts


def test_year_counts_tallies_and_drops_missing_years():
    df = pd.DataFrame(
        {"year": [2020, 2020, 2019, pd.NA]},
    )
    out = year_counts(df)
    assert list(out.columns) == ["year", "n"]
    # The missing-year row is dropped, not counted.
    assert out["n"].sum() == 3
    counts = dict(zip(out["year"], out["n"]))
    assert counts == {2019: 1, 2020: 2}
    # Sorted ascending by year, with integer dtypes.
    assert list(out["year"]) == [2019, 2020]
    assert out["year"].dtype.kind == "i"
    assert out["n"].dtype.kind == "i"


def test_trend_frame_sorts_and_shapes():
    out = _trend_frame({2021: 5, 2019: 2, 2020: 9})
    assert list(out.columns) == ["year", "n"]
    assert list(out["year"]) == [2019, 2020, 2021]
    assert list(out["n"]) == [2, 9, 5]


def test_scopus_trend_validates_inputs():
    with pytest.raises(ValueError):
        scopus_trend("", [2020])
    with pytest.raises(ValueError):
        scopus_trend("graphene", [])
