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


def test_records_with_a_blank_identifier_are_dropped_as_well(fake_pybliometrics_corpus):
    # scopus_abstract() refuses a blank identifier and points to corpus(),
    # so corpus() has to drop it.
    records = pd.DataFrame({
        "doi": ["10.1/a", "  ", ""], "title": ["A", "B", "C"], "year": [2020, 2021, 2022],
    })
    with pytest.warns(UserWarning, match="Dropped 2"):
        out = corpus(records, view="FULL")
    assert list(out["title"]) == ["A"]


def test_corpus_carries_through_the_quota_accounting(fake_pybliometrics_corpus):
    # The wrapper that spends the most quota must report what it spent; a
    # freshly constructed frame carries no attrs of its own.
    records = pd.DataFrame({"doi": ["10.1/a"], "title": ["A study"], "year": [2020]})
    out = corpus(records, view="FULL")
    assert out.attrs["n_requests"] == 1
    assert "quota" in out.attrs


def test_corpus_under_ref_asks_for_references_only(fake_pybliometrics_corpus, monkeypatch):
    # The REF response carries no author keywords, so asking for them spent
    # nothing extra but returned a keywords column that only looked empty.
    # The R twin requests references alone under REF.
    # The package exports the function under the module's own name.
    corpus_module = sys.modules["scopusflow.corpus"]

    seen = []
    real = corpus_module.scopus_abstract

    def spy(ids, **kwargs):
        seen.append((kwargs["view"], tuple(kwargs["include"])))
        return real(ids, **kwargs)

    monkeypatch.setattr(corpus_module, "scopus_abstract", spy)
    records = pd.DataFrame({"doi": ["10.1/a"], "title": ["A study"], "year": [2020]})
    out = corpus(records, view="REF")
    assert seen == [("REF", ("references",))]
    assert out.loc[0, "keywords"] == []
    assert len(out.loc[0, "references"]) == 1

    seen.clear()
    corpus(records, view="FULL")
    assert seen == [("FULL", ("references", "keywords"))]


@pytest.fixture
def fake_pybliometrics_index_terms(monkeypatch):
    """A stand-in pybliometrics whose documents carry author and index keywords,
    recording each identifier it is asked for."""
    from pybliometrics.scopus import Reference

    calls = []

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            calls.append(ident)
            return types.SimpleNamespace(
                eid="2-s2.0-85000000001", doi=ident, title=None, description=None,
                publicationName=None, coverDate="2020-01-01", citedby_count=None,
                authkeywords=["graphene", "Supercapacitors"],
                idxterms=["Supercapacitors", "Graphene", "Electrodes"],
                references=None,
            )

    pkg = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.AbstractRetrieval = _AbstractRetrieval
    scopus.Reference = Reference
    pkg.scopus = scopus
    monkeypatch.setitem(sys.modules, "pybliometrics", pkg)
    monkeypatch.setitem(sys.modules, "pybliometrics.scopus", scopus)
    return calls


def test_keywords_index_and_both_draw_on_the_index_keywords(fake_pybliometrics_index_terms):
    records = pd.DataFrame({"doi": ["10.1/a"], "title": ["A study"], "year": [2020]})
    # The default is unchanged: the author keywords alone.
    assert corpus(records).loc[0, "keywords"] == ["graphene", "Supercapacitors"]
    assert corpus(records, keywords="index").loc[0, "keywords"] == [
        "Supercapacitors", "Graphene", "Electrodes",
    ]
    # Author keywords first, then each index keyword not already among them. The
    # match is on the exact text, so "graphene" and "Graphene" are both kept.
    assert corpus(records, keywords="both").loc[0, "keywords"] == [
        "graphene", "Supercapacitors", "Graphene", "Electrodes",
    ]


def test_each_keywords_choice_asks_scopus_abstract_for_what_it_needs(
    fake_pybliometrics_index_terms, monkeypatch
):
    corpus_module = sys.modules["scopusflow.corpus"]
    seen = []
    real = corpus_module.scopus_abstract

    def spy(ids, **kwargs):
        seen.append(tuple(kwargs["include"]))
        return real(ids, **kwargs)

    monkeypatch.setattr(corpus_module, "scopus_abstract", spy)
    records = pd.DataFrame({"doi": ["10.1/a"], "title": ["A study"], "year": [2020]})
    for keywords in ("author", "index", "both"):
        corpus(records, keywords=keywords)
    assert seen == [
        ("references", "keywords"),
        ("references", "index_terms"),
        ("references", "keywords", "index_terms"),
    ]


@pytest.mark.parametrize("keywords", ["index", "both"])
def test_index_keywords_need_full_and_ref_refuses_them_before_a_request(
    fake_pybliometrics_index_terms, keywords
):
    records = pd.DataFrame({"doi": ["10.1/a"], "title": ["A study"], "year": [2020]})
    with pytest.raises(ValueError, match='view="FULL"'):
        corpus(records, view="REF", keywords=keywords)
    assert fake_pybliometrics_index_terms == []


def test_an_unknown_keywords_choice_is_refused(fake_pybliometrics_index_terms):
    records = pd.DataFrame({"doi": ["10.1/a"], "title": ["A study"], "year": [2020]})
    with pytest.raises(ValueError, match="keywords must be"):
        corpus(records, keywords="authors")
    assert fake_pybliometrics_index_terms == []


def test_corpus_validates_input_shape():
    with pytest.raises(ValueError):
        corpus(pd.DataFrame({"x": [1]}))
    with pytest.raises(ValueError):
        corpus(pd.DataFrame({"doi": [None], "title": ["x"], "year": [2020]}))
