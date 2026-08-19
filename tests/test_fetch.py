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


def test_a_standard_resume_refetches_a_complete_written_checkpoint(tmp_path):
    # The query alone cannot tell the two views apart, and a COMPLETE-written
    # checkpoint would hand a STANDARD resume an authkeywords column the
    # documentation promises STANDARD output never carries. The authkeywords
    # column itself betrays the origin, so even a checkpoint from before the
    # view was recorded is caught in this direction.
    import pandas as pd

    complete_cell = pd.DataFrame([{
        "entry_number": 1, "scopus_id": "1", "doi": "10.1/complete", "title": None,
        "authors": None, "year": pd.NA, "date": None, "publication": None,
        "citations": pd.NA, "query": "TITLE(x)", "authkeywords": "graphene",
    }])
    complete_cell.to_csv(tmp_path / "cell-001.csv", index=False)

    records = [{"eid": "2-s2.0-9", "doi": "10.1/fresh"}]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter)
        plan = SearchPlan("x", field="TITLE")   # view="STANDARD" by default
        with pytest.warns(UserWarning, match="different plan"):
            out = fetch_plan(plan, cache_dir=str(tmp_path), resume=True)
        assert counter["n"] == 1
        assert list(out["doi"]) == ["10.1/fresh"]
        assert "authkeywords" not in out.columns
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def test_a_complete_resume_refetches_a_checkpoint_recorded_as_standard(tmp_path):
    # New checkpoints record the view they were written under, so the mismatch
    # is detectable in this direction too, where no column gives it away. A
    # checkpoint from before the view was recorded is still accepted under
    # COMPLETE as old rather than foreign (see
    # test_fetch_plan_resume_with_mixed_schema_does_not_error).
    records = [{"eid": "2-s2.0-1", "doi": "10.1/a"}]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter)
        fetch_plan(SearchPlan("x", field="TITLE"), cache_dir=str(tmp_path))
        assert counter["n"] == 1

        plan = SearchPlan("x", field="TITLE", view="COMPLETE")
        with pytest.warns(UserWarning, match="different plan"):
            out = fetch_plan(plan, cache_dir=str(tmp_path), resume=True)
        assert counter["n"] == 2
        assert "authkeywords" in out.columns
        # The recorded view stays a checkpoint detail, not an output column.
        assert "view" not in out.columns
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


@pytest.mark.parametrize("fmt", ["parquet", "csv"])
def test_a_half_written_checkpoint_is_refetched_rather_than_aborting_the_run(tmp_path, fmt):
    # A checkpoint that cannot be read back must cost one refetch, not every
    # subsequent resume: an unreadable file the caller has to find and delete by
    # hand defeats the point of resuming at all.
    #
    # Parametrised over the format rather than left to whatever _write_checkpoint
    # picks, because the two paths fail in different ways and running only the one
    # the local environment happens to produce is exactly how the CSV hole
    # survived: _write_checkpoint falls back to CSV when no parquet engine is
    # installed, so this exercised parquet on a developer machine with pyarrow and
    # CSV on CI without it, and only CI ever saw the branch that was broken.
    import warnings as warnings_module

    if fmt == "parquet":
        pytest.importorskip("pyarrow", reason="no parquet engine to write with")

    records = [{"eid": "2-s2.0-1", "doi": "10.1/a"}, {"eid": "2-s2.0-2", "doi": "10.1/b"}]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter)
        plan = SearchPlan("x", field="TITLE")
        fetch_plan(plan, cache_dir=str(tmp_path), resume=True, format=fmt)

        checkpoint = next(p for p in tmp_path.iterdir() if p.name.startswith("cell-"))
        assert checkpoint.suffix == f".{fmt}"
        if fmt == "parquet":
            # Truncated past its footer, so pyarrow refuses it outright.
            checkpoint.write_bytes(checkpoint.read_bytes()[:8])
        else:
            # A CSV cannot be damaged into raising so easily: a truncated one is
            # still well-formed, and a row wider than its header does not raise
            # either, because pandas takes the surplus leading field as an index
            # and hands back a tidy frame. What gives it away is the schema, which
            # no longer carries the columns the checkpoint was written with.
            checkpoint.write_text("a,b\n1,2,3\n")

        with pytest.warns(UserWarning) as caught:
            out = fetch_plan(plan, cache_dir=str(tmp_path), resume=True, format=fmt)
        assert str(caught[0].message) == (
            f"The checkpoint {checkpoint} could not be read back, so it was "
            "discarded and the cell refetched. An interrupted run can leave a "
            "checkpoint half-written."
        )
        assert counter["n"] == 2      # the damaged cell was fetched again
        assert len(out) == 2

        # The damaged checkpoint has been replaced in place, rather than left on
        # disk beside a good one of the other format, so the next resume is clean.
        assert [p.name for p in sorted(tmp_path.iterdir())] == [checkpoint.name]
        with warnings_module.catch_warnings():
            warnings_module.simplefilter("error")
            fetch_plan(plan, cache_dir=str(tmp_path), resume=True, format=fmt)
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


def test_fetch_plan_carries_per_cell_accounting_and_provenance(tmp_path):
    records = [{"eid": "2-s2.0-1", "doi": "10.1/a"}, {"eid": "2-s2.0-2", "doi": "10.1/b"}]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter, total=2)
        plan = SearchPlan("x", years=[2018, 2019, 2020], partition="year")
        out = fetch_plan(plan)

        cells = out.attrs["cell_totals"]
        assert list(cells["cell"]) == [1, 2, 3]
        assert list(cells["date"]) == ["2018", "2019", "2020"]
        assert list(cells["n_records"]) == [2, 2, 2]
        assert list(cells["reported_total"]) == [2, 2, 2]
        assert out.attrs["total_results"] == 6
        assert out.attrs["plan"] == plan
        assert out.attrs["paging"] == "cursor"
        assert out.attrs["retrieved_at"].tzinfo is not None
        assert out.attrs["scopusflow_version"] == sf_version()
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def test_an_overall_total_needs_every_cell_to_have_reported_one(tmp_path):
    # A resumed cell reports no total, the count not being part of what a
    # checkpoint stores, so the sum would understate the search.
    records = [{"eid": "2-s2.0-1", "doi": "10.1/a"}]
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics(records, counter, total=1)
        plan = SearchPlan("x", years=[2019, 2020], partition="year")
        fetch_plan(plan, cache_dir=str(tmp_path))
        resumed = fetch_plan(plan, cache_dir=str(tmp_path))

        assert list(resumed.attrs["cell_totals"]["reported_total"]) == [None, None]
        assert resumed.attrs["total_results"] is None
        # An undatable cell leaves the whole set undated rather than letting it
        # claim a time later than one of the cells inside it.
        assert "retrieved_at" not in resumed.attrs
        assert "scopusflow_version" not in resumed.attrs
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def test_the_plans_page_size_is_what_is_requested():
    seen = {}

    class _Search:
        def __init__(self, query, **kwargs):
            seen.update(kwargs)
            self.results = []

    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        pybliometrics = types.ModuleType("pybliometrics")
        scopus = types.ModuleType("pybliometrics.scopus")
        scopus.ScopusSearch = _Search
        pybliometrics.scopus = scopus
        sys.modules["pybliometrics"] = pybliometrics
        sys.modules["pybliometrics.scopus"] = scopus

        fetch_plan(SearchPlan("x", page_size=50))
        assert seen["count"] == 50
        seen.clear()
        fetch_plan(SearchPlan("x", view="COMPLETE"))
        assert seen["count"] == 25
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def sf_version() -> str:
    from scopusflow import __version__

    return __version__
