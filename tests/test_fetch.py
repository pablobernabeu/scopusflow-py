"""Offline tests for the resumable fetch layer (no API key, no pybliometrics)."""

import json
import sys
import time
import types
import warnings
from datetime import datetime, timedelta, timezone

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


def test_cell_query_brackets_a_query_whose_top_level_operator_would_swallow_the_year():
    # Scopus applies AND NOT last, so "A AND NOT B AND PUBYEAR IS 2015" reads
    # as A AND NOT (B AND PUBYEAR IS 2015) and the cell returns every year.
    exclusion = "TITLE-ABS-KEY(hypertension) AND NOT TITLE-ABS-KEY(pulmonary)"
    assert _cell_query(exclusion, 2015, None) == (
        "(TITLE-ABS-KEY(hypertension) AND NOT TITLE-ABS-KEY(pulmonary)) "
        "AND PUBYEAR IS 2015"
    )
    # Under the order Elsevier has announced (AND NOT, AND, OR) it is an OR
    # that loses the limit, so OR is bracketed too, in every form of the fold.
    union = "TITLE-ABS-KEY(CRISPR) OR TITLE-ABS-KEY(Cas9)"
    assert _cell_query(union, None, "2015-2020") == (
        "(TITLE-ABS-KEY(CRISPR) OR TITLE-ABS-KEY(Cas9)) "
        "AND PUBYEAR AFT 2014 AND PUBYEAR BEF 2021"
    )
    assert _cell_query(union, None, "2019") == (
        "(TITLE-ABS-KEY(CRISPR) OR TITLE-ABS-KEY(Cas9)) AND PUBYEAR IS 2019"
    )
    # An OR inside a field tag is already grouped by the tag's own brackets.
    assert _cell_query("TITLE(CRISPR OR Cas9)", 2019, None) == (
        "TITLE(CRISPR OR Cas9) AND PUBYEAR IS 2019"
    )


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


def _checkpoint_for(query: str):
    import pandas as pd

    return pd.DataFrame([{
        "entry_number": 1, "scopus_id": "1", "doi": "10.1/cached", "title": None,
        "authors": None, "year": pd.NA, "date": None, "publication": None,
        "citations": pd.NA, "query": query,
    }])


def test_an_operator_free_plan_still_resumes_from_its_existing_checkpoint(tmp_path):
    # Bracketing is applied only where a query needs it, so a checkpoint
    # written before the change is still served to the plan that wrote it,
    # without a request.
    _checkpoint_for("TITLE(x) AND PUBYEAR IS 2019").to_csv(
        tmp_path / "cell-001.csv", index=False
    )
    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics([{"eid": "2-s2.0-9", "doi": "10.1/fresh"}], counter)
        plan = SearchPlan("x", field="TITLE", years=[2019], partition="year")
        out = fetch_plan(plan, cache_dir=str(tmp_path), resume=True)
        assert counter["n"] == 0
        assert list(out["doi"]) == ["10.1/cached"]
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def test_an_and_not_plan_refetches_its_unbracketed_checkpoint_once(tmp_path):
    # The checkpoint holds records fetched under the regrouped query, so it
    # must not be served. Its recorded query differs from the bracketed one,
    # which the existing different-plan check already catches, and the
    # refetched cell is then resumed normally.
    base = "TITLE(hypertension) AND NOT TITLE(pulmonary)"
    _checkpoint_for(f"{base} AND PUBYEAR IS 2019").to_csv(
        tmp_path / "cell-001.csv", index=False
    )
    counter = {"n": 0}
    sent = []
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics([{"eid": "2-s2.0-9", "doi": "10.1/fresh"}], counter)
        fake = sys.modules["pybliometrics.scopus"].ScopusSearch

        class RecordingSearch(fake):
            def __init__(self, query, **kwargs):
                sent.append(query)
                super().__init__(query, **kwargs)

        sys.modules["pybliometrics.scopus"].ScopusSearch = RecordingSearch
        plan = SearchPlan(base, years=[2019], partition="year")
        with pytest.warns(UserWarning, match="different plan"):
            out = fetch_plan(plan, cache_dir=str(tmp_path), resume=True)
        assert counter["n"] == 1
        assert sent == [f"({base}) AND PUBYEAR IS 2019"]
        assert list(out["doi"]) == ["10.1/fresh"]
        assert list(out["query"]) == [f"({base}) AND PUBYEAR IS 2019"]

        again = fetch_plan(plan, cache_dir=str(tmp_path), resume=True)
        assert counter["n"] == 1
        assert list(again["doi"]) == ["10.1/fresh"]
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

        checkpoint = next(p for p in tmp_path.iterdir()
                          if p.name.startswith("cell-") and p.suffix != ".json")
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
        assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
            [checkpoint.name, "cell-001.json"]
        )
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
        # Sort both sides: ".csv" sorts before ".json" and ".parquet" after it.
        assert sorted(p.name for p in tmp_path.iterdir()) == sorted([
            "cell-001.json", f"cell-001{suffix}", "cell-002.json", f"cell-002{suffix}",
        ])
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


def test_a_harvest_records_the_view_it_was_fetched_under(monkeypatch):
    # The view decides what the authors column holds, the first author under
    # STANDARD and the author list under COMPLETE, so top() reads it back.
    class _Search:
        def __init__(self, query, **kwargs):
            self.results = [{"eid": "2-s2.0-1", "doi": "10.1/a", "creator": "Cong L."}]

    _use_search(monkeypatch, _Search)
    assert fetch_plan(SearchPlan("x")).attrs["view"] == "STANDARD"
    assert fetch_plan(SearchPlan("x", view="COMPLETE")).attrs["view"] == "COMPLETE"


def test_a_resumed_complete_checkpoint_has_its_authors_joined_as_now(tmp_path):
    # A checkpoint written before the join changed holds pybliometrics' bare
    # ';'. Joining it again on resume costs nothing, so it is never refetched,
    # and a cell with no authors keeps its missing value.
    import pandas as pd

    old = pd.DataFrame([
        {"entry_number": 1, "scopus_id": "1", "doi": "10.1/old", "title": None,
         "authors": "Cong, Le;Zhang, Feng", "year": pd.NA, "date": None,
         "publication": None, "citations": pd.NA, "query": "TITLE(x)",
         "authkeywords": None, "view": "COMPLETE"},
        {"entry_number": 2, "scopus_id": "2", "doi": "10.1/none", "title": None,
         "authors": None, "year": pd.NA, "date": None,
         "publication": None, "citations": pd.NA, "query": "TITLE(x)",
         "authkeywords": None, "view": "COMPLETE"},
    ])
    old.to_csv(tmp_path / "cell-001.csv", index=False)

    counter = {"n": 0}
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    try:
        _install_fake_pybliometrics([], counter)
        plan = SearchPlan("x", field="TITLE", view="COMPLETE")
        out = fetch_plan(plan, cache_dir=str(tmp_path), resume=True)
        assert counter["n"] == 0
        assert out.loc[0, "authors"] == "Cong, Le; Zhang, Feng"
        assert pd.isna(out.loc[1, "authors"])
        assert out.attrs["view"] == "COMPLETE"
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

        # Every attribute is held in a JSON-safe form, so the harvest can be
        # saved with its provenance (see tests/test_io.py).
        assert out.attrs["cell_totals"] == [
            {"cell": 1, "date": "2018", "n_records": 2, "reported_total": 2},
            {"cell": 2, "date": "2019", "n_records": 2, "reported_total": 2},
            {"cell": 3, "date": "2020", "n_records": 2, "reported_total": 2},
        ]
        assert out.attrs["total_results"] == 6
        assert out.attrs["plan"] == plan.to_dict()
        assert SearchPlan.from_dict(out.attrs["plan"]) == plan
        assert out.attrs["paging"] == "cursor"
        assert datetime.fromisoformat(out.attrs["retrieved_at"]).utcoffset() == timedelta(0)
        assert out.attrs["scopusflow_version"] == sf_version()
    finally:
        for key, mod in saved.items():
            if mod is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = mod


def _counting_search(monkeypatch, records, total=None):
    """Install a stand-in ScopusSearch that records each query it is sent and
    reports ``total`` (by default the number of records) as the API's count."""
    sent = []

    class _Search:
        def __init__(self, query, **kwargs):
            sent.append(query)
            self.results = list(records)

        def get_results_size(self):
            return len(records) if total is None else total

    _use_search(monkeypatch, _Search)
    return sent


def _manifest(directory, cell=1):
    return json.loads((directory / f"cell-{cell:03d}.json").read_text(encoding="utf-8"))


def _write_manifest(directory, manifest, cell=1):
    (directory / f"cell-{cell:03d}.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_each_checkpoint_has_a_manifest_saying_how_it_was_fetched(monkeypatch, tmp_path):
    _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}], total=3)
    plan = SearchPlan("x", field="TITLE", years=[2019], partition="year", page_size=50)
    with pytest.warns(UserWarning, match="harvest may be incomplete"):
        out = fetch_plan(plan, cache_dir=str(tmp_path))
    manifest = _manifest(tmp_path)
    assert manifest == {
        "schema": 1,
        "query": "TITLE(x) AND PUBYEAR IS 2019",
        "view": "STANDARD",
        "page_size": 50,
        "paging": "cursor",
        "n_records": 1,
        "reported_total": 3,
        "retrieved_at": out.attrs["retrieved_at"],
        "scopusflow_version": sf_version(),
    }


def test_a_count_given_as_a_numpy_integer_is_recorded_as_a_plain_one(monkeypatch, tmp_path):
    # json.dumps cannot write a NumPy integer, and failing there would end the
    # harvest after the cell had been paid for.
    import numpy as np

    sent = _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}])
    plan = SearchPlan("x")
    fetch_plan(plan, cache_dir=str(tmp_path), count=np.int64(25))
    assert _manifest(tmp_path)["page_size"] == 25
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fetch_plan(plan, cache_dir=str(tmp_path), count=np.int64(25))
    assert len(sent) == 1


def test_a_zero_row_checkpoint_is_not_served_to_a_different_query(monkeypatch, tmp_path):
    # Mirrors the R twin's test-cache.R. An empty cell has no query values in
    # its rows, so only the manifest's own copy of the query can reject it.
    sent = _counting_search(monkeypatch, [], total=0)
    fetch_plan(SearchPlan("perovskite", years=[2016], partition="year"),
               cache_dir=str(tmp_path))
    assert len(sent) == 1

    plan_b = SearchPlan("graphene", years=[2016], partition="year")
    with pytest.warns(UserWarning, match="different plan"):
        out = fetch_plan(plan_b, cache_dir=str(tmp_path))
    assert sent[1:] == ["graphene AND PUBYEAR IS 2016"]
    assert len(out) == 0

    # The overwritten checkpoint then serves its own query without a request.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fetch_plan(plan_b, cache_dir=str(tmp_path))
    assert len(sent) == 2


def test_an_empty_early_year_cannot_hide_a_populated_one(monkeypatch, tmp_path):
    # The same query with only its years shifted: cell 1 was 1990, empty, and
    # is now 2016, where the literature is.
    _counting_search(monkeypatch, [], total=0)
    fetch_plan(SearchPlan("graphene", years=[1990], partition="year"),
               cache_dir=str(tmp_path))

    sent = _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}])
    with pytest.warns(UserWarning, match="different plan"):
        out = fetch_plan(SearchPlan("graphene", years=[2016], partition="year"),
                         cache_dir=str(tmp_path))
    assert sent == ["graphene AND PUBYEAR IS 2016"]
    assert list(out["doi"]) == ["10.1/a"]


@pytest.mark.parametrize(("field", "value"), [("page_size", 100), ("paging", "offset"),
                                              ("view", "COMPLETE")])
def test_a_manifest_that_differs_in_how_the_cell_was_paged_is_refetched(
    monkeypatch, tmp_path, field, value
):
    sent = _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}])
    plan = SearchPlan("x", page_size=50)
    fetch_plan(plan, cache_dir=str(tmp_path))
    _write_manifest(tmp_path, {**_manifest(tmp_path), field: value})

    with pytest.warns(UserWarning, match="different plan"):
        fetch_plan(plan, cache_dir=str(tmp_path))
    assert len(sent) == 2
    assert _manifest(tmp_path)[field] != value


def test_a_manifest_backed_resume_keeps_each_cells_total_time_and_version(
    monkeypatch, tmp_path
):
    # The R twin restores all three from its checkpoints, so the search record
    # of a resumed harvest can state its date and completeness.
    sent = _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}], total=1)
    plan = SearchPlan("x", years=[2019, 2020], partition="year")
    first = fetch_plan(plan, cache_dir=str(tmp_path))
    resumed = fetch_plan(plan, cache_dir=str(tmp_path))

    assert len(sent) == 2
    assert [c["reported_total"] for c in resumed.attrs["cell_totals"]] == [1, 1]
    assert resumed.attrs["total_results"] == 2
    assert resumed.attrs["retrieved_at"] == first.attrs["retrieved_at"]
    assert resumed.attrs["scopusflow_version"] == sf_version()

    from scopusflow.report import scopus_search_report

    record = scopus_search_report(resumed).format(style="report")
    assert "Completeness: every record the API reported as matching was retrieved" in record
    assert "Date searched: unrecorded" not in record


def test_a_resumed_set_is_dated_by_its_earliest_cell_and_lists_every_version(
    monkeypatch, tmp_path
):
    # As the R twin combines them: a set is only as fresh as its oldest cell,
    # and a cache written by an earlier release means more than one version
    # built the set.
    sent = _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}], total=1)
    plan = SearchPlan("x", years=[2019, 2020], partition="year")
    fetch_plan(plan, cache_dir=str(tmp_path))
    _write_manifest(tmp_path, {**_manifest(tmp_path), "scopusflow_version": "0.3.9",
                               "retrieved_at": "2026-01-02T03:04:05+00:00"})
    for path in tmp_path.glob("cell-002.*"):
        path.unlink()

    out = fetch_plan(plan, cache_dir=str(tmp_path))
    assert len(sent) == 3
    assert out.attrs["retrieved_at"] == "2026-01-02T03:04:05+00:00"
    assert out.attrs["scopusflow_version"] == sorted(["0.3.9", sf_version()])
    assert out.attrs["total_results"] == 2


def test_a_checkpoint_without_a_manifest_resumes_as_before(monkeypatch, tmp_path):
    # A checkpoint written before manifests existed, or one whose manifest an
    # interruption kept from being written, is served on its recorded query
    # alone and carries no total, time or version.
    sent = _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}], total=1)
    plan = SearchPlan("x", years=[2019, 2020], partition="year")
    fetch_plan(plan, cache_dir=str(tmp_path))
    for path in tmp_path.glob("cell-*.json"):
        path.unlink()

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        resumed = fetch_plan(plan, cache_dir=str(tmp_path))
    assert len(sent) == 2
    assert [c["reported_total"] for c in resumed.attrs["cell_totals"]] == [None, None]
    assert resumed.attrs["total_results"] is None
    # An undatable cell leaves the whole set undated rather than letting it
    # claim a time later than one of the cells inside it.
    assert "retrieved_at" not in resumed.attrs
    assert "scopusflow_version" not in resumed.attrs


def test_a_manifest_without_its_checkpoint_is_ignored(monkeypatch, tmp_path):
    sent = _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}])
    plan = SearchPlan("x")
    fetch_plan(plan, cache_dir=str(tmp_path))
    stale = {**_manifest(tmp_path), "retrieved_at": "2026-01-02T03:04:05+00:00"}
    _write_manifest(tmp_path, stale)
    next(p for p in tmp_path.glob("cell-001.*") if p.suffix != ".json").unlink()

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = fetch_plan(plan, cache_dir=str(tmp_path))
    assert len(sent) == 2
    assert out.attrs["retrieved_at"] != stale["retrieved_at"]
    assert _manifest(tmp_path)["retrieved_at"] == out.attrs["retrieved_at"]


def test_an_old_manifest_is_removed_before_its_checkpoint_is_replaced(monkeypatch, tmp_path):
    # Should the run stop between the two writes, the new checkpoint is left
    # without a manifest, never beside the old one.
    import scopusflow.fetch as fetch_module

    _counting_search(monkeypatch, [], total=0)
    fetch_plan(SearchPlan("perovskite"), cache_dir=str(tmp_path))

    def interrupted(frame, cache, cell, fmt):
        raise KeyboardInterrupt

    _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}])
    monkeypatch.setattr(fetch_module, "_write_checkpoint", interrupted)
    with pytest.warns(UserWarning, match="different plan"), pytest.raises(KeyboardInterrupt):
        fetch_plan(SearchPlan("graphene"), cache_dir=str(tmp_path))
    assert not (tmp_path / "cell-001.json").exists()


@pytest.mark.parametrize(
    ("rows", "expected"),
    [([{"eid": "2-s2.0-9", "doi": "10.1/z"}], "different plan"),
     ([], "not written together")],
)
def test_a_checkpoint_replaced_beside_its_manifest_is_not_served_under_it(
    monkeypatch, tmp_path, rows, expected
):
    # An earlier version writing into the same directory replaces the
    # checkpoint and leaves the manifest in place. The rows' own query betrays
    # a populated replacement, and the row count an empty one.
    import pandas as pd

    from scopusflow.records import to_records

    sent = _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}])
    plan = SearchPlan("perovskite")
    fetch_plan(plan, cache_dir=str(tmp_path), format="csv")
    replacement = (to_records(rows, query="graphene") if rows
                   else pd.DataFrame(columns=RECORD_COLUMNS))
    replacement.to_csv(tmp_path / "cell-001.csv", index=False)

    with pytest.warns(UserWarning, match=expected):
        out = fetch_plan(plan, cache_dir=str(tmp_path), format="csv")
    assert len(sent) == 2
    assert list(out["doi"]) == ["10.1/a"]


def test_empty_checkpoints_without_a_manifest_are_refetched_with_one_warning(
    monkeypatch, tmp_path
):
    # An empty checkpoint from an earlier version cannot say which search wrote
    # it, so it costs one request, and the harvest warns once for all of them.
    import pandas as pd

    for cell in (1, 2):
        pd.DataFrame(columns=RECORD_COLUMNS).to_csv(tmp_path / f"cell-{cell:03d}.csv",
                                                    index=False)
    sent = _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}])
    plan = SearchPlan("x", years=[2019, 2020], partition="year")
    with pytest.warns(UserWarning) as caught:
        out = fetch_plan(plan, cache_dir=str(tmp_path))
    assert len(sent) == 2
    assert len(out) == 2
    assert [str(w.message) for w in caught] == [
        f"2 empty checkpoints in {tmp_path} (cells 1, 2) have no manifest to say "
        "which search wrote them, so those cells were fetched again. Checkpoints "
        "written by earlier versions of scopusflow have none."
    ]
    assert _manifest(tmp_path, 2)["n_records"] == 1

    # A single cell is named in the singular.
    from scopusflow.fetch import _legacy_empty_warning

    assert _legacy_empty_warning([3], tmp_path) == (
        f"1 empty checkpoint in {tmp_path} (cell 3) has no manifest to say which "
        "search wrote it, so that cell was fetched again. Checkpoints written by "
        "earlier versions of scopusflow have none."
    )


def test_a_manifest_that_cannot_be_read_costs_one_refetch(monkeypatch, tmp_path):
    sent = _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}])
    plan = SearchPlan("x")
    fetch_plan(plan, cache_dir=str(tmp_path))
    (tmp_path / "cell-001.json").write_text('{"schema": 1, "query"', encoding="utf-8")

    with pytest.warns(UserWarning, match="manifest beside the checkpoint .* could not be read"):
        fetch_plan(plan, cache_dir=str(tmp_path))
    assert len(sent) == 2
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fetch_plan(plan, cache_dir=str(tmp_path))
    assert len(sent) == 2


def test_a_new_checkpoint_replaces_one_of_the_other_format(monkeypatch, tmp_path):
    # Otherwise the old parquet file, which resume looks for first, would be
    # found beside the manifest written for the new CSV one.
    pytest.importorskip("pyarrow", reason="no parquet engine to write with")
    _counting_search(monkeypatch, [{"eid": "2-s2.0-1", "doi": "10.1/a"}])
    fetch_plan(SearchPlan("perovskite"), cache_dir=str(tmp_path), format="parquet")
    fetch_plan(SearchPlan("graphene"), cache_dir=str(tmp_path), format="csv", resume=False)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cell-001.csv", "cell-001.json"]


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


#: A cache file's time in the tests below. It is fixed, and far from any change
#: of the clocks, so its local rendering reads back as the same instant in
#: every time zone.
_WRITTEN = datetime(2026, 7, 1, 9, 30, 15, tzinfo=timezone.utc)


def _rendered(timestamp: float) -> str:
    """A time as pybliometrics' ``get_cache_file_mdate()`` renders it."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def _use_search(monkeypatch, search_class):
    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.ScopusSearch = search_class
    pkg = types.ModuleType("pybliometrics")
    pkg.scopus = scopus
    monkeypatch.setitem(sys.modules, "pybliometrics", pkg)
    monkeypatch.setitem(sys.modules, "pybliometrics.scopus", scopus)


class _CachedCell:
    """What pybliometrics hands back for a query it answers from its own cache:
    the cached rows, their number as the result size, the file's local time and
    no response headers."""

    def __init__(self, query, **kwargs):
        self.results = [{"eid": "2-s2.0-1", "doi": "10.1/a"}]

    def get_results_size(self):
        return 1

    def get_cache_file_mdate(self):
        return _rendered(_WRITTEN.timestamp())

    def get_key_remaining_quota(self):
        return None


def test_every_cell_is_sent_with_refresh_unless_the_caller_sends_it(monkeypatch):
    # pybliometrics answers a query it has filed from its own cache unless
    # refresh is True, so scopusflow sends True unless told otherwise.
    sent = []

    class _Search:
        def __init__(self, query, **kwargs):
            sent.append(kwargs.get("refresh", "not sent"))
            self.results = []

    _use_search(monkeypatch, _Search)
    fetch_plan(SearchPlan("x", years=[2019, 2020], partition="year"))
    assert sent == [True, True]
    sent.clear()
    fetch_plan(SearchPlan("x"), refresh=False)
    fetch_plan(SearchPlan("x"), refresh=30)
    assert sent == [False, 30]


def test_a_cell_served_from_pybliometrics_cache_is_dated_by_the_file(monkeypatch, tmp_path):
    _use_search(monkeypatch, _CachedCell)
    with pytest.warns(UserWarning, match="pybliometrics' own cache") as caught:
        out = fetch_plan(SearchPlan("x", field="TITLE"), cache_dir=str(tmp_path),
                         refresh=False)
    assert len(caught) == 1
    assert str(caught[0].message).startswith("Cell 1 was served from")
    assert "2026-07-01 09:30:15 UTC" in str(caught[0].message)
    # A cached answer gives its own row count as the total, which proves
    # nothing about what the API holds.
    assert [c["reported_total"] for c in out.attrs["cell_totals"]] == [None]
    assert out.attrs["total_results"] is None
    assert out.attrs["retrieved_at"] == "2026-07-01T09:30:15+00:00"


def test_a_cell_whose_cache_time_cannot_be_read_is_left_undated(monkeypatch):
    class _Unreadable(_CachedCell):
        def get_cache_file_mdate(self):
            return "yesterday"

    _use_search(monkeypatch, _Unreadable)
    with pytest.warns(UserWarning, match="could not be read"):
        out = fetch_plan(SearchPlan("x"), refresh=False)
    assert [c["reported_total"] for c in out.attrs["cell_totals"]] == [None]
    assert out.attrs["total_results"] is None
    assert "retrieved_at" not in out.attrs


def test_a_fresh_answer_under_refresh_false_keeps_its_total_and_time(monkeypatch):
    class _Fresh:
        def __init__(self, query, **kwargs):
            self._answered = time.time()
            self.results = [{"eid": "2-s2.0-1", "doi": "10.1/a"}]

        def get_results_size(self):
            return 1

        def get_cache_file_mdate(self):
            return _rendered(self._answered)

        def get_key_remaining_quota(self):
            return "19999"

    _use_search(monkeypatch, _Fresh)
    before = datetime.now(timezone.utc)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = fetch_plan(SearchPlan("x"), refresh=False)
    assert out.attrs["total_results"] == 1
    # The stamp is kept to the second, as the search record shows it.
    assert datetime.fromisoformat(out.attrs["retrieved_at"]) >= before.replace(microsecond=0)


def test_the_default_takes_pybliometrics_answer_as_fetched(monkeypatch):
    # Under refresh=True pybliometrics always makes the request, so the cache
    # getters are not consulted and cannot misdate a fresh cell.
    class _Search:
        def __init__(self, query, **kwargs):
            self.results = [{"eid": "2-s2.0-1", "doi": "10.1/a"}]

        def get_results_size(self):
            return 1

        def get_cache_file_mdate(self):
            raise AssertionError("consulted under refresh=True")

        def get_key_remaining_quota(self):
            raise AssertionError("consulted under refresh=True")

    _use_search(monkeypatch, _Search)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = fetch_plan(SearchPlan("x"))
    assert out.attrs["total_results"] == 1


def sf_version() -> str:
    from scopusflow import __version__

    return __version__
