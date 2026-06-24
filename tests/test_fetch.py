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


def _install_fake_pybliometrics(records, counter):
    """Inject a fake pybliometrics exposing a counting ScopusSearch."""
    pybliometrics = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")

    class ScopusSearch:
        def __init__(self, query, **kwargs):
            counter["n"] += 1
            self.results = list(records)

    scopus.ScopusSearch = ScopusSearch
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


def test_fetch_plan_validates_plan_and_format(tmp_path):
    with pytest.raises(ValueError):
        fetch_plan("not a plan", cache_dir=str(tmp_path))
    with pytest.raises(ValueError):
        fetch_plan(SearchPlan("x"), cache_dir=str(tmp_path), format="json")
