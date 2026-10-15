"""Offline tests for the publication-trend layer (no API key, no pybliometrics)."""

import json
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import scopusflow as sf
from scopusflow.plan import SearchPlan
from scopusflow.trend import _incomplete_note, _trend_frame, scopus_trend, year_counts

FIXTURES = Path(__file__).parent / "fixtures"


def _trend_years():
    """The record sets and retrieval times the R suite reads too, byte for byte."""
    return json.loads((FIXTURES / "trend-years.json").read_text(encoding="utf-8"))


def _records_for(case):
    """A frame holding only the years of one counts case, with its plan and, for
    a stopped harvest, the attributes fetch_plan() records."""
    records = pd.DataFrame({"year": pd.array(case["record_years"], dtype="Int64")})
    plan = case["plan"]
    if plan is not None:
        records.attrs["plan"] = SearchPlan(
            plan["query"], years=plan["years"], partition=plan["partition"]
        ).to_dict()
    stopped = case.get("stopped")
    if stopped is not None:
        records.attrs.update({
            "stopped_early": True,
            "cells_planned": stopped["cells_planned"],
            "cells_run": stopped["cells_run"],
            "cell_totals": stopped["cell_totals"],
        })
    return records


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


def test_year_counts_includes_a_year_without_records():
    # The bundled corpus without 2018 jumped from 2017 to 2019, so plot_trend()
    # drew a line straight across the missing year.
    records = sf.example_records()
    gapped = records[records["year"] != 2018]
    counts = dict(zip(*(year_counts(gapped)[c] for c in ("year", "n")), strict=True))
    assert counts[2018] == 0
    assert sorted(counts) == list(range(2015, 2025))
    # fill=False gives the years that hold records, as before.
    assert 2018 not in list(year_counts(gapped, fill=False)["year"])


def test_year_counts_cover_the_years_searched_as_the_r_twin_does():
    for case in _trend_years()["counts"]:
        out = year_counts(_records_for(case))
        assert list(out["year"]) == case["years"], case["name"]
        assert list(out["n"]) == case["n"], case["name"]
        assert out["year"].dtype.kind == "i", case["name"]
        assert out["n"].dtype.kind == "i", case["name"]


def test_year_counts_without_fill_keeps_only_the_years_with_records():
    case = _trend_years()["counts"][0]  # year cells with a gap
    out = year_counts(_records_for(case), fill=False)
    assert list(out["year"]) == [2015, 2016, 2020]
    assert list(out["n"]) == [2, 1, 1]


def test_year_counts_carries_the_retrieval_time():
    # plot_trend() reads it, as the R twin's autoplot() reads the records' own.
    records = pd.DataFrame({"year": [2025, 2026]})
    records.attrs["retrieved_at"] = "2026-09-29T10:15:00+00:00"
    assert year_counts(records).attrs["retrieved_at"] == "2026-09-29T10:15:00+00:00"
    assert "retrieved_at" not in year_counts(pd.DataFrame({"year": [2025]})).attrs


def test_the_incomplete_note_reads_the_recorded_time_as_the_r_twin_does():
    for case in _trend_years()["notes"]:
        assert _incomplete_note(case["years"], case["retrieved_at"]) == case["note"], case


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


def _use_search(monkeypatch, search_class):
    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.ScopusSearch = search_class
    pkg = types.ModuleType("pybliometrics")
    pkg.scopus = scopus
    monkeypatch.setitem(sys.modules, "pybliometrics", pkg)
    monkeypatch.setitem(sys.modules, "pybliometrics.scopus", scopus)


def test_every_year_is_counted_with_refresh_unless_the_caller_sends_it(monkeypatch):
    # pybliometrics answers a query an earlier harvest filed with the number
    # of rows it cached, unless refresh is True.
    sent = []

    class _Search:
        def __init__(self, query, **kwargs):
            sent.append(kwargs.get("refresh", "not sent"))

        def get_results_size(self):
            return 5

    _use_search(monkeypatch, _Search)
    scopus_trend("graphene", [2019, 2020])
    assert sent == [True, True]
    sent.clear()
    scopus_trend("graphene", [2019], refresh=False)
    assert sent == [False]


def test_a_year_counted_from_pybliometrics_cache_is_warned_about(monkeypatch):
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
        out = scopus_trend("graphene", [2019], refresh=False)
    assert list(out["n"]) == [2]
    message = str(caught[0].message)
    assert "'graphene AND PUBYEAR IS 2019'" in message
    assert "2026-07-01 09:30:15 UTC" in message
    assert "not the API's total" in message


def test_scopus_trend_records_when_it_counted(monkeypatch):
    class _Search:
        def __init__(self, query, **kwargs):
            pass

        def get_results_size(self):
            return 5

    _use_search(monkeypatch, _Search)
    before = datetime.now(timezone.utc).replace(microsecond=0)
    out = scopus_trend("graphene", [2019, 2020])
    after = datetime.now(timezone.utc)
    stamp = datetime.fromisoformat(out.attrs["retrieved_at"])
    assert before <= stamp <= after


def test_a_trend_counted_from_pybliometrics_cache_is_dated_by_its_file(monkeypatch):
    written = datetime(2026, 7, 1, 9, 30, 15, tzinfo=timezone.utc)
    mdate = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(written.timestamp()))

    class _Cached:
        def __init__(self, query, **kwargs):
            pass

        def get_results_size(self):
            return 2

        def get_cache_file_mdate(self):
            return mdate

        def get_key_remaining_quota(self):
            return None

    _use_search(monkeypatch, _Cached)
    with pytest.warns(UserWarning, match="pybliometrics' own cache"):
        out = scopus_trend("graphene", [2019], refresh=False)
    assert out.attrs["retrieved_at"] == "2026-07-01T09:30:15+00:00"

    # A cached count whose file time cannot be read leaves the trend undated.
    mdate = "not a time"
    with pytest.warns(UserWarning, match="could not be read"):
        out = scopus_trend("graphene", [2019], refresh=False)
    assert "retrieved_at" not in out.attrs


def test_scopus_trend_brackets_a_query_whose_operators_would_swallow_the_year():
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
        scopus_trend("TITLE-ABS-KEY(CRISPR) OR TITLE-ABS-KEY(Cas9)", [2019, 2020])
        assert queries == [
            "(TITLE-ABS-KEY(CRISPR) OR TITLE-ABS-KEY(Cas9)) AND PUBYEAR IS 2019",
            "(TITLE-ABS-KEY(CRISPR) OR TITLE-ABS-KEY(Cas9)) AND PUBYEAR IS 2020",
        ]
        queries.clear()
        scopus_trend("TITLE(hypertension) AND NOT TITLE(pulmonary)", [2015])
        assert queries == [
            "(TITLE(hypertension) AND NOT TITLE(pulmonary)) AND PUBYEAR IS 2015"
        ]
    finally:
        for k, mod in saved.items():
            if mod is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = mod
