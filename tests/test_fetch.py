"""Offline tests for the resumable fetch layer (no API key, no pybliometrics)."""

import sys
import types

import pytest

from scopusflow.fetch import _cell_query, fetch_plan
from scopusflow.plan import SearchPlan
from scopusflow.records import RECORD_COLUMNS


def test_cell_query_folds_year_date_and_none():
    base = "TITLE(x)"
    # An explicit year wins.
    assert _cell_query(base, 2020, None) == "TITLE(x) AND PUBYEAR IS 2020"
    # A "YYYY-YYYY" range expands to an open interval.
    assert _cell_query(base, None, "2015-2020") == (
        "TITLE(x) AND PUBYEAR AFT 2014 AND PUBYEAR BEF 2021"
    )
    # A single "YYYY" date folds to an equality.
    assert _cell_query(base, None, "2019") == "TITLE(x) AND PUBYEAR IS 2019"
    # No constraint leaves the query untouched.
    assert _cell_query(base, None, None) == base


def _install_fake_pybliometrics(records, counter, total=None):
    """Inject a fake pybliometrics exposing a counting ScopusSearch.

    ``total`` gives the double a ``get_results_size()``; leaving it ``None``
    keeps the double as minimal as the installed pybliometrics might be, which
    the shortfall check must tolerate rather than raise on.
    """
    pybliometrics = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")

    class ScopusSearch:
        def __init__(self, query, **kwargs):
            counter["n"] += 1
            self.results = list(records)

    class CountingScopusSearch(ScopusSearch):
        def get_results_size(self):
            return total

    scopus.ScopusSearch = ScopusSearch if total is None else CountingScopusSearch
    pybliometrics.scopus = scopus
    sys.modules["pybliometrics"] = pybliometrics
    sys.modules["pybliometrics.scopus"] = scopus


def test_fetch_plan_end_to_end_offline(tmp_path):
    records = [
        {
            "eid": "2-s2.0-85000000001",
            "doi": "10.1/a",
            "title": "A study",
            "author_names": "Smith J.",
            "coverDate": "2020-05-01",
            "publicationName": "Journal",
            "citedby_count": "3",
        },
        {
            "eid": "2-s2.0-85000000002",
            "doi": "10.1/b",
            "title": "B study",
            "author_names": "Doe A.",
            "coverDate": "2020-07-01",
            "publicationName": "Journal",
            "citedby_count": "1",
        },
    ]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter)

        plan = SearchPlan("x", field="TITLE")
        out = fetch_plan(plan, cache_dir=str(tmp_path))

        # (a) the stable schema and the expected row count.
        assert list(out.columns) == RECORD_COLUMNS
        assert len(out) == 2
        assert list(out["entry_number"]) == [1, 2]
        assert counter["n"] == 1

        # (b) a checkpoint is written, in parquet when pyarrow is available and the
        # CSV fallback otherwise; exactly one of the two formats should exist.
        parquet_ckpt = tmp_path / "cell-001.parquet"
        csv_ckpt = tmp_path / "cell-001.csv"
        assert parquet_ckpt.exists() != csv_ckpt.exists()

        # (c) resume reads the checkpoint and does not re-instantiate ScopusSearch.
        again = fetch_plan(plan, cache_dir=str(tmp_path), resume=True)
        assert counter["n"] == 1
        assert list(again.columns) == RECORD_COLUMNS
        assert len(again) == 2
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def test_fetch_plan_refetches_a_checkpoint_written_by_a_different_plan(tmp_path):
    # A cache_dir belongs to one plan: a checkpoint whose recorded query does
    # not match the cell's must be warned about and refetched, not returned.
    import pandas as pd

    stale = pd.DataFrame([{
        "entry_number": 1, "scopus_id": "1", "doi": "10.1/stale", "title": None,
        "authors": None, "year": pd.NA, "date": None, "publication": None,
        "citations": pd.NA, "query": "TITLE(perovskite)",
    }])
    stale.to_csv(tmp_path / "cell-001.csv", index=False)

    records = [{"eid": "2-s2.0-9", "doi": "10.1/fresh"}]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter)
        plan = SearchPlan("graphene", field="TITLE")
        with pytest.warns(UserWarning, match="different plan"):
            out = fetch_plan(plan, cache_dir=str(tmp_path), resume=True)
        assert counter["n"] == 1
        assert list(out["doi"]) == ["10.1/fresh"]
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def test_a_half_written_checkpoint_is_refetched_rather_than_aborting_the_run(tmp_path):
    # A checkpoint that cannot be read back must cost one refetch, not every
    # subsequent resume: an unreadable file the caller has to find and delete by
    # hand defeats the point of resuming at all.
    import warnings as warnings_module

    records = [{"eid": "2-s2.0-1", "doi": "10.1/a"}, {"eid": "2-s2.0-2", "doi": "10.1/b"}]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter)
        plan = SearchPlan("x", field="TITLE")
        fetch_plan(plan, cache_dir=str(tmp_path), resume=True)

        # What an interrupted or killed run leaves behind. A truncated CSV still
        # parses, so the CSV fallback is damaged in a way a reader can detect
        # instead, a row wider than its header.
        checkpoint = next(p for p in tmp_path.iterdir() if p.name.startswith("cell-"))
        if checkpoint.suffix == ".parquet":
            checkpoint.write_bytes(checkpoint.read_bytes()[:8])
        else:
            checkpoint.write_text("a,b\n1,2,3\n")

        with pytest.warns(UserWarning) as caught:
            out = fetch_plan(plan, cache_dir=str(tmp_path), resume=True)
        assert str(caught[0].message) == (
            f"The checkpoint {checkpoint} could not be read back, so it was "
            "discarded and the cell refetched. An interrupted run can leave a "
            "checkpoint half-written."
        )
        assert counter["n"] == 2      # the damaged cell was fetched again
        assert len(out) == 2

        # The damaged checkpoint has been replaced, so the next resume is clean.
        with warnings_module.catch_warnings():
            warnings_module.simplefilter("error")
            fetch_plan(plan, cache_dir=str(tmp_path), resume=True)
        assert counter["n"] == 2
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def test_a_checkpoint_is_written_whole_or_not_at_all(tmp_path):
    # The temporary file the atomic write uses must not be left behind, and must
    # never be mistaken for a checkpoint.
    records = [{"eid": "2-s2.0-1", "doi": "10.1/a"}]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter)
        plan = SearchPlan("x", years=[2019, 2020], partition="year")
        fetch_plan(plan, cache_dir=str(tmp_path))
        suffix = ".parquet" if (tmp_path / "cell-001.parquet").exists() else ".csv"
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            f"cell-001{suffix}", f"cell-002{suffix}",
        ]
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def test_fetch_plan_validates_plan_and_format(tmp_path):
    with pytest.raises(ValueError):
        fetch_plan("not a plan", cache_dir=str(tmp_path))
    with pytest.raises(ValueError):
        fetch_plan(SearchPlan("x"), cache_dir=str(tmp_path), format="json")


def test_fetch_plan_complete_view_carries_authkeywords(tmp_path):
    records = [{
        "eid": "2-s2.0-85000000001",
        "doi": "10.1/a",
        "authkeywords": "graphene | supercapacitor",
    }]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter)
        plan = SearchPlan("x", field="TITLE", view="COMPLETE")
        out = fetch_plan(plan, cache_dir=str(tmp_path))
        assert "authkeywords" in out.columns
        assert out.loc[0, "authkeywords"] == "graphene | supercapacitor"
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def test_fetch_plan_resume_with_mixed_schema_does_not_error(tmp_path):
    # Simulates upgrading scopusflow mid-harvest: an older cached cell lacks
    # the authkeywords column entirely, while a newly fetched cell has it.
    import pandas as pd

    old_cell = pd.DataFrame([{
        "entry_number": 1, "scopus_id": "1", "doi": "10.1/old", "title": None,
        "authors": None, "year": pd.NA, "date": None, "publication": None,
        "citations": pd.NA, "query": "x AND PUBYEAR IS 2019",
    }])
    # CSV, not parquet: the fixture must not depend on an optional engine that
    # may be absent (mirrors fetch_plan()'s own to-CSV fallback).
    old_cell.to_csv(tmp_path / "cell-001.csv", index=False)

    records = [{"eid": "2-s2.0-2", "doi": "10.1/new", "authkeywords": "graphene"}]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter)
        plan = SearchPlan("x", years=[2019, 2020], partition="year", view="COMPLETE")
        out = fetch_plan(plan, cache_dir=str(tmp_path), resume=True)
        assert len(out) == 2
        assert "authkeywords" in out.columns
        old_row = out[out["doi"] == "10.1/old"].iloc[0]
        new_row = out[out["doi"] == "10.1/new"].iloc[0]
        assert pd.isna(old_row["authkeywords"])
        assert new_row["authkeywords"] == "graphene"
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def test_resuming_a_csv_checkpoint_keeps_identifiers_out_of_float_land(tmp_path):
    # CSV carries no types, so an inferred read turns an all-digits Scopus ID
    # into 85012345678.0 and a nullable year or citation count into NaN. The
    # resumed rows must come back as they were written.
    import pandas as pd

    from scopusflow.records import to_records

    written = to_records(
        [
            {"eid": "2-s2.0-85012345678", "doi": "10.1/a",
             "coverDate": "2020-01-01", "citedby_count": "3"},
            {"eid": None, "doi": None},
        ],
        query="TITLE(x)",
    )
    written.to_csv(tmp_path / "cell-001.csv", index=False)

    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics([], counter)
        plan = SearchPlan("x", field="TITLE")
        out = fetch_plan(plan, cache_dir=str(tmp_path), resume=True)
        assert counter["n"] == 0  # served from the checkpoint
        assert list(out["scopus_id"]) == ["85012345678", pd.NA]
        assert out.loc[0, "year"] == 2020
        assert out.loc[0, "citations"] == 3
        assert pd.isna(out.loc[1, "year"])
        # The exported row must not carry a float-shaped identifier.
        from scopusflow.export import to_ris
        assert "N1  - Scopus ID: 85012345678\n" in to_ris(out)
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def test_fetch_plan_warns_when_a_cell_falls_short_of_the_reported_total(tmp_path):
    # A truncated or failed download arrives as a merely small frame, so the
    # cell's row count is compared against the API's own reported total.
    records = [{"eid": "2-s2.0-1", "doi": "10.1/a"}]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter, total=25)
        plan = SearchPlan("x", field="TITLE")
        with pytest.warns(UserWarning, match="harvest may be incomplete"):
            out = fetch_plan(plan, cache_dir=str(tmp_path))
        assert out.attrs["total_results"] == 25
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def test_fetch_plan_is_quiet_when_the_cell_is_complete_or_reports_no_total(tmp_path):
    import warnings as warnings_module

    records = [{"eid": "2-s2.0-1", "doi": "10.1/a"}]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter, total=1)
        with warnings_module.catch_warnings():
            warnings_module.simplefilter("error")
            out = fetch_plan(SearchPlan("x", field="TITLE"), cache_dir=str(tmp_path))
        assert out.attrs["total_results"] == 1

        # A double with no get_results_size (as an older pybliometrics, or a
        # minimal stand-in, may be) must degrade rather than raise.
        _install_fake_pybliometrics(records, counter)
        with warnings_module.catch_warnings():
            warnings_module.simplefilter("error")
            bare = fetch_plan(SearchPlan("y", field="TITLE"))
        assert bare.attrs["total_results"] is None
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod
