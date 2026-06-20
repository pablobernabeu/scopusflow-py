"""Offline tests for abstract retrieval (no API key, fake pybliometrics)."""

import sys
import types

import pandas as pd
import pytest

from scopusflow.abstract import ABSTRACT_COLUMNS, _abstract_row, scopus_abstract


def test_abstract_row_from_dict():
    obj = {
        "eid": "2-s2.0-85000000001",
        "doi": "10.1/a",
        "title": "A study",
        "description": "An abstract.",
        "publicationName": "Journal",
        "coverDate": "2020-05-01",
        "citedby_count": "7",
    }
    row = _abstract_row(obj)
    assert row["scopus_id"] == "85000000001"
    assert row["year"] == 2020
    assert isinstance(row["year"], int)
    assert row["citations"] == 7
    assert isinstance(row["citations"], int)
    assert row["abstract"] == "An abstract."


def test_abstract_row_from_namespace():
    obj = types.SimpleNamespace(
        eid="2-s2.0-85000000002",
        doi="10.1/b",
        title="Another",
        description="Text.",
        publicationName="Cell",
        coverDate="2019-01-01",
        citedby_count="3",
    )
    row = _abstract_row(obj)
    assert row["scopus_id"] == "85000000002"
    assert row["year"] == 2019
    assert isinstance(row["year"], int)
    assert row["citations"] == 3
    assert isinstance(row["citations"], int)


@pytest.fixture
def fake_pybliometrics():
    """Insert a fake pybliometrics whose AbstractRetrieval fails for "bad"."""
    good = types.SimpleNamespace(
        eid="2-s2.0-85000000009",
        doi="10.1/good",
        title="Good paper",
        description="A real abstract.",
        publicationName="Nature",
        coverDate="2021-03-01",
        citedby_count="12",
    )

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            if ident == "10.1/bad":
                raise RuntimeError("boom")
            return good

    saved = {
        name: sys.modules.get(name)
        for name in ("pybliometrics", "pybliometrics.scopus")
    }
    pkg = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.AbstractRetrieval = _AbstractRetrieval
    pkg.scopus = scopus
    sys.modules["pybliometrics"] = pkg
    sys.modules["pybliometrics.scopus"] = scopus
    try:
        yield
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


def test_scopus_abstract_is_resilient_per_id(fake_pybliometrics):
    with pytest.warns(UserWarning, match="10.1/bad"):
        df = scopus_abstract(["10.1/bad", "10.1/good"], by="doi")
    assert list(df.columns) == ABSTRACT_COLUMNS
    assert len(df) == 2

    bad = df.iloc[0]
    assert bad["doi"] == "10.1/bad"
    assert pd.isna(bad["title"])
    assert pd.isna(bad["scopus_id"])
    assert pd.isna(bad["abstract"])

    good = df.iloc[1]
    assert good["doi"] == "10.1/good"
    assert good["scopus_id"] == "85000000009"
    assert good["title"] == "Good paper"
    assert good["year"] == 2021
    assert good["citations"] == 12


def test_scopus_abstract_rejects_invalid_by():
    with pytest.raises(ValueError):
        scopus_abstract("10.1/a", by="title")
