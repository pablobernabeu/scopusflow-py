"""Offline tests for corpus(), which enriches records with keywords/references."""

import sys
import types

import pandas as pd
import pytest

from scopusflow.corpus import corpus


@pytest.fixture
def fake_pybliometrics_corpus():
    from pybliometrics.scopus import Reference

    refs = [
        Reference(
            position="1", id="1", doi="10.1/cited", title="A cited work",
            authors=None, authors_auid=None, authors_affiliationid=None,
            sourcetitle="Some Journal", publicationyear="2019", coverDate=None,
            volume=None, issue=None, first=None, last=None, citedbycount=None,
            type=None, text=None, fulltext=None,
        ),
    ]
    rich = types.SimpleNamespace(
        eid="2-s2.0-85000000001", doi="10.1/a", title="Ignored (records wins)",
        description="An abstract.", publicationName="Journal", coverDate="2020-01-01",
        citedby_count="3", authkeywords=["graphene", "supercapacitor"], references=refs,
    )

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            return rich

    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
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
        for k, mod in saved.items():
            if mod is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = mod


def test_corpus_assembles_id_title_year_keywords_references(fake_pybliometrics_corpus):
    records = pd.DataFrame({"doi": ["10.1/a"], "title": ["A study"], "year": [2020]})
    out = corpus(records, view="FULL")
    assert list(out.columns) == ["id", "title", "year", "keywords", "references"]
    assert out.loc[0, "id"] == "10.1/a"          # from records, not the abstract response
    assert out.loc[0, "title"] == "A study"       # from records, not the abstract response
    assert out.loc[0, "year"] == 2020
    assert out.loc[0, "keywords"] == ["graphene", "supercapacitor"]
    refs = out.loc[0, "references"]
    assert len(refs) == 1
    assert refs.loc[0, "title"] == "A cited work"


def test_a_document_with_no_keywords_gets_an_empty_not_na_list():
    good = types.SimpleNamespace(
        eid="2-s2.0-1", doi="10.1/a", title=None, description=None,
        publicationName=None, coverDate=None, citedby_count=None,
        authkeywords=None, references=None,
    )

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            return good

    from pybliometrics.scopus import Reference
    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    pkg = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.AbstractRetrieval = _AbstractRetrieval
    scopus.Reference = Reference
    pkg.scopus = scopus
    sys.modules["pybliometrics"] = pkg
    sys.modules["pybliometrics.scopus"] = scopus
    try:
        records = pd.DataFrame({"doi": ["10.1/a"], "title": ["A"], "year": [2020]})
        out = corpus(records, view="FULL")
        assert out.loc[0, "keywords"] == []
    finally:
        for k, mod in saved.items():
            if mod is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = mod


def test_records_with_a_missing_identifier_are_dropped_with_a_warning(fake_pybliometrics_corpus):
    records = pd.DataFrame({
        "doi": ["10.1/a", None], "title": ["A", "B"], "year": [2020, 2021],
    })
    with pytest.warns(UserWarning, match="Dropped 1"):
        out = corpus(records, view="FULL")
    assert len(out) == 1
    assert out.loc[0, "title"] == "A"


def test_corpus_validates_input_shape():
    with pytest.raises(ValueError):
        corpus(pd.DataFrame({"x": [1]}))
    with pytest.raises(ValueError):
        corpus(pd.DataFrame({"doi": [None], "title": ["x"], "year": [2020]}))
