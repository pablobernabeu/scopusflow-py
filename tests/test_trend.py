"""Offline tests for the publication-trend layer (no API key, no pybliometrics)."""

import sys
import types

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
    counts = dict(zip(out["year"], out["n"], strict=True))
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
    # An invalid field tag is refused before any request, as in scopus_count().
    with pytest.raises(ValueError):
        scopus_trend("graphene", [2020], field="not a tag")


def test_scopus_trend_wraps_the_field_once_before_the_year_loop():
    # The field tag applies to the query, not the year filter folded in beside
    # it, matching scopus_count() and the R twin's scopus_trend().
    queries = []

    class _ScopusSearch:
        def __init__(self, query, **kwargs):
            queries.append(query)

        def get_results_size(self):
            return 5

    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    pkg = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.ScopusSearch = _ScopusSearch
    pkg.scopus = scopus
    sys.modules["pybliometrics"] = pkg
    sys.modules["pybliometrics.scopus"] = scopus
    try:
        out = scopus_trend("graphene", [2019, 2020], field="TITLE-ABS-KEY")
        assert queries == [
            "TITLE-ABS-KEY(graphene) AND PUBYEAR IS 2019",
            "TITLE-ABS-KEY(graphene) AND PUBYEAR IS 2020",
        ]
        assert list(out["year"]) == [2019, 2020]
        assert list(out["n"]) == [5, 5]

        # Left None, the query is sent as given (the behaviour before field).
        queries.clear()
        scopus_trend("graphene", [2019])
        assert queries == ["graphene AND PUBYEAR IS 2019"]
    finally:
        for k, mod in saved.items():
            if mod is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = mod
