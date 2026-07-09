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


def test_without_view_or_include_output_columns_are_exactly_as_before(fake_pybliometrics):
    df = scopus_abstract("10.1/good", by="doi")
    assert list(df.columns) == ABSTRACT_COLUMNS


def test_include_and_view_are_validated():
    with pytest.raises(ValueError):
        scopus_abstract("x", include=("wrongthing",))
    with pytest.raises(ValueError):
        scopus_abstract("x", include=("references",))  # default view="META_ABS" is incompatible
    with pytest.raises(ValueError):
        scopus_abstract("x", view="META", include=("references",))


@pytest.fixture
def fake_pybliometrics_rich():
    """A fake pybliometrics whose AbstractRetrieval carries authkeywords and a
    references list of real pybliometrics Reference namedtuples, plus a fake
    pybliometrics.exception module so the Scopus403Error import succeeds."""
    from pybliometrics.scopus import Reference

    refs = [
        Reference(
            position="1", id="84878919540", doi="10.1000/imagenet",
            title="ImageNet classification with deep CNNs",
            authors="Krizhevsky, A.", authors_auid=None, authors_affiliationid=None,
            sourcetitle="Proc. NeurIPS", publicationyear="2012", coverDate=None,
            volume="25", issue=None, first=None, last=None, citedbycount=None,
            type="resolved", text=None, fulltext=None,
        ),
    ]
    rich = types.SimpleNamespace(
        eid="2-s2.0-85000000010", doi="10.1/rich", title="A rich record",
        description="An abstract.", publicationName="Nature", coverDate="2021-01-01",
        citedby_count="78713", authkeywords=["graphene", "supercapacitor"],
        references=refs,
        get_key_remaining_quota=lambda: "9987",
        get_key_reset_time=lambda: "2026-01-01 00:00:00",
    )

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            return rich

    saved = {
        name: sys.modules.get(name)
        for name in ("pybliometrics", "pybliometrics.scopus")
    }
    pkg = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.AbstractRetrieval = _AbstractRetrieval
    scopus.Reference = Reference
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


def test_a_reference_list_shorter_than_refcount_is_warned_about():
    """A mocked document reports refcount=3 but returns one reference; the
    documented incomplete-page safeguard must warn rather than stay silent."""
    import warnings as _warnings

    from pybliometrics.scopus import Reference

    from scopusflow.abstract import _abstract_row

    ref = Reference(
        position="1", id="1", doi="10.1/ref", title="A cited work",
        authors=None, authors_auid=None, authors_affiliationid=None,
        sourcetitle=None, publicationyear=None, coverDate=None,
        volume=None, issue=None, first=None, last=None, citedbycount=None,
        type="resolved", text=None, fulltext=None,
    )
    obj = types.SimpleNamespace(
        eid="2-s2.0-1", doi="10.1/partial", title="T", description="A.",
        publicationName="J", coverDate="2020-01-01", citedby_count="1",
        references=[ref], refcount="3",
    )
    with pytest.warns(UserWarning, match="refcount=3"):
        row = _abstract_row(obj, include=("references",))
    assert len(row["references"]) == 1

    # A matching count stays silent.
    obj.refcount = "1"
    with _warnings.catch_warnings():
        _warnings.simplefilter("error")
        _abstract_row(obj, include=("references",))


def test_include_keywords_under_full_view_adds_a_populated_column(fake_pybliometrics_rich):
    df = scopus_abstract("10.1/rich", view="FULL", include=("keywords",))
    assert "authkeywords" in df.columns
    assert df.loc[0, "authkeywords"] == "graphene; supercapacitor"


def test_include_references_under_full_view_returns_a_structured_frame(fake_pybliometrics_rich):
    df = scopus_abstract("10.1/rich", view="FULL", include=("references",))
    assert "references" in df.columns
    refs = df.loc[0, "references"]
    assert len(refs) == 1
    assert refs.loc[0, "title"] == "ImageNet classification with deep CNNs"
    assert refs.loc[0, "doi"] == "10.1000/imagenet"
    assert refs.loc[0, "sourcetitle"] == "Proc. NeurIPS"


def test_include_references_reports_n_requests_and_quota(fake_pybliometrics_rich):
    df = scopus_abstract("10.1/rich", view="FULL", include=("references", "keywords"))
    assert df.attrs["n_requests"] == 1
    assert df.attrs["quota"]["remaining"] == "9987"


def test_a_document_with_no_references_yields_a_zero_row_frame():
    from pybliometrics.scopus import Reference

    good = types.SimpleNamespace(
        eid="2-s2.0-1", doi="10.1/x", title=None, description=None,
        publicationName=None, coverDate=None, citedby_count=None,
        authkeywords=None, references=None,
    )

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            return good

    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    pkg = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.AbstractRetrieval = _AbstractRetrieval
    scopus.Reference = Reference
    pkg.scopus = scopus
    sys.modules["pybliometrics"] = pkg
    sys.modules["pybliometrics.scopus"] = scopus
    try:
        df = scopus_abstract("10.1/x", view="FULL", include=("references", "keywords"))
        refs = df.loc[0, "references"]
        assert len(refs) == 0
        assert pd.isna(df.loc[0, "authkeywords"])
    finally:
        for k, mod in saved.items():
            if mod is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = mod


def test_an_entitlement_403_stops_the_batch_with_a_clear_actionable_message():
    from scopusflow.exceptions import ScopusFlowForbiddenError

    calls = {"n": 0}

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            calls["n"] += 1
            raise _Scopus403Error("forbidden")

    saved = {
        name: sys.modules.get(name)
        for name in ("pybliometrics", "pybliometrics.scopus", "pybliometrics.exception")
    }
    pkg = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")
    exception_mod = types.ModuleType("pybliometrics.exception")

    global _Scopus403Error

    class _Scopus403Error(Exception):
        pass

    exception_mod.Scopus403Error = _Scopus403Error
    scopus.AbstractRetrieval = _AbstractRetrieval
    pkg.scopus = scopus
    pkg.exception = exception_mod
    sys.modules["pybliometrics"] = pkg
    sys.modules["pybliometrics.scopus"] = scopus
    sys.modules["pybliometrics.exception"] = exception_mod
    try:
        with pytest.raises(ScopusFlowForbiddenError, match="FULL"):
            scopus_abstract(
                ["10.1/a", "10.1/b", "10.1/c"], view="FULL", include=("references",)
            )
        # Stops at the first 403 rather than repeating the same failure three times.
        assert calls["n"] == 1
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


def test_caching_writes_per_identifier_files_and_resume_avoids_refetching(tmp_path, fake_pybliometrics_rich):
    df1 = scopus_abstract("10.1/rich", view="FULL", include=("references",), cache_dir=str(tmp_path))
    assert len(list(tmp_path.glob("id-*.pkl"))) == 1

    # Break AbstractRetrieval so a second, non-cached call would fail; resume
    # must still succeed by reading the cache instead of re-fetching.
    sys.modules["pybliometrics.scopus"].AbstractRetrieval = None
    df2 = scopus_abstract("10.1/rich", view="FULL", include=("references",), cache_dir=str(tmp_path))
    assert df2.loc[0, "doi"] == df1.loc[0, "doi"]
