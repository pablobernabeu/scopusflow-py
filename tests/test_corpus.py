"""Offline tests for corpus(), which enriches records with keywords/references,
and for the writer of theoryforge's corpus schema."""

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import scopusflow as sf
from scopusflow.corpus import corpus, to_theoryforge_corpus, write_corpus


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
    assert list(out.columns) == ["id", "scopus_id", "title", "year", "keywords", "references"]
    assert out.loc[0, "id"] == "10.1/a"          # from records, not the abstract response
    assert out.loc[0, "scopus_id"] == "85000000001"  # the document's own, from its EID
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


@pytest.fixture
def fake_pybliometrics_one_missing(monkeypatch):
    """A stand-in pybliometrics that finds 10.1/a, under a Scopus identifier of
    its own, and fails on 10.1/missing."""
    from pybliometrics.scopus import Reference

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            if ident == "10.1/missing":
                raise RuntimeError("not in Scopus")
            return types.SimpleNamespace(
                eid="2-s2.0-85000000002", doi=ident, title=None, description=None,
                publicationName=None, coverDate="2020-01-01", citedby_count=None,
                authkeywords=None, references=None,
            )

    pkg = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.AbstractRetrieval = _AbstractRetrieval
    scopus.Reference = Reference
    pkg.scopus = scopus
    monkeypatch.setitem(sys.modules, "pybliometrics", pkg)
    monkeypatch.setitem(sys.modules, "pybliometrics.scopus", scopus)


def test_corpus_takes_the_scopus_id_from_the_abstract_else_the_records(
    fake_pybliometrics_one_missing,
):
    # The corpus writer keys records on this identifier. Neither twin returned
    # it, so a corpus looked up by DOI could not say which document a row was.
    records = pd.DataFrame({
        "scopus_id": ["85000000001", "85000000009"],
        "doi": ["10.1/a", "10.1/missing"],
        "title": ["A", "B"],
        "year": [2020, 2021],
    })
    with pytest.warns(UserWarning, match="missing"):
        out = corpus(records)
    assert list(out.columns) == ["id", "scopus_id", "title", "year", "keywords", "references"]
    assert list(out["scopus_id"]) == ["85000000002", "85000000009"]
    assert out.attrs["n_requests"] == 2
    assert "quota" in out.attrs

    # Records without the column, and a lookup that fails, leave it missing.
    with pytest.warns(UserWarning, match="missing"):
        out = corpus(records.drop(columns="scopus_id").iloc[1:])
    assert pd.isna(out.loc[0, "scopus_id"])


def test_corpus_carries_the_search_expression_its_date_and_the_kind_of_keyword(
    fake_pybliometrics_index_terms,
):
    from scopusflow import SearchPlan

    records = pd.DataFrame({"doi": ["10.1/a"], "title": ["A"], "year": [2020]})
    records.attrs["plan"] = SearchPlan("graphene", years=[2020], field="TITLE-ABS-KEY").to_dict()
    records.attrs["retrieved_at"] = "2026-10-02T09:15:00+00:00"
    out = corpus(records, keywords="index")
    assert out.attrs["query"] == ["TITLE-ABS-KEY(graphene)"]
    assert out.attrs["retrieved_at"] == "2026-10-02T09:15:00+00:00"
    assert out.attrs["keywords"] == "index"

    # Without a plan, the records' own query column states the expression, as
    # it does in the search record. With neither, nothing is recorded.
    records = pd.DataFrame({"doi": ["10.1/a"], "title": ["A"], "year": [2020],
                            "query": ["TITLE(graphene)"]})
    assert corpus(records).attrs["query"] == ["TITLE(graphene)"]
    out = corpus(records.drop(columns="query"))
    assert out.attrs["query"] is None
    assert out.attrs["retrieved_at"] is None


# The corpus writer. Its shared fixture and golden sit in the R suite too, byte
# for byte, so the twins write the same file from the same corpus.

_TESTS = Path(__file__).resolve().parent


def _writer_fixture():
    """The two-document corpus behind the golden, in the shape corpus()
    returns, with the attributes it attaches. Years are nullable Int64, as a
    resumed checkpoint holds them."""
    fx = json.loads((_TESTS / "fixtures" / "corpus-writer.json").read_text(encoding="utf-8"))
    rows = fx["records"]

    def text(value):
        return pd.NA if value is None else value

    frame = pd.DataFrame({
        "id": [r["id"] for r in rows],
        "scopus_id": [text(r["scopus_id"]) for r in rows],
        "title": [text(r["title"]) for r in rows],
        "year": pd.array([r["year"] for r in rows], dtype="Int64"),
        "keywords": [r["keywords"] for r in rows],
        "references": [
            pd.DataFrame(r["references"], columns=["position", "id", "doi"]) for r in rows
        ],
    })
    frame.attrs.update(fx["attributes"])
    return fx["id"], frame


def _golden_form(path) -> str:
    """What write_corpus() wrote, as the golden holds it: the running version
    replaced by a placeholder, so that a version bump leaves the golden alone."""
    written = Path(path).read_bytes().decode("utf-8")
    return written.replace(f"scopusflow {sf.__version__}", "scopusflow <version>", 1)


def test_write_corpus_writes_the_shared_golden(tmp_path):
    corpus_id, frame = _writer_fixture()
    path = tmp_path / "corpus.json"
    with pytest.warns(UserWarning, match="1 reference"):
        write_corpus(frame, path, corpus_id)
    assert _golden_form(path) == (_TESTS / "golden-corpus.json").read_bytes().decode("utf-8")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["provenance"]["source"] == f"Scopus via scopusflow {sf.__version__}"


def test_the_golden_and_the_written_corpus_validate_against_theoryforge_schema(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    if not hasattr(jsonschema, "Draft202012Validator"):
        pytest.skip("Draft 2020-12 needs jsonschema 4.0 or later")
    schema = json.loads((_TESTS / "fixtures" / "corpus.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    validator.validate(json.loads((_TESTS / "golden-corpus.json").read_text(encoding="utf-8")))
    corpus_id, frame = _writer_fixture()
    with pytest.warns(UserWarning):
        validator.validate(to_theoryforge_corpus(frame, corpus_id))


def test_the_writer_keys_a_cited_work_on_its_scopus_id_however_its_doi_is_written():
    # Keyed on the DOI where present, as theoryforge's earlier recipe did, W and
    # X split into two nodes each and the co-citation edge between them was lost.
    corpus_id, frame = _writer_fixture()
    with pytest.warns(UserWarning, match="1 reference"):
        doc = to_theoryforge_corpus(frame, corpus_id)
    assert doc["schema_version"] == "1.0"
    assert doc["id"] == "graphene-supercapacitors"
    # B carries no identifier of its own, and takes the one A's bibliography
    # gives its DOI, so a citation of B and B itself are one key.
    assert [r["id"] for r in doc["records"]] == ["scopus:85000000001", "scopus:85000000002"]
    assert doc["records"][0]["references"] == [
        "scopus:111", "scopus:222", "doi:10.5555/z", "scopus:85000000002",
    ]
    assert doc["records"][1]["references"] == ["scopus:111", "scopus:222", "scopus:85000000001"]
    assert doc["records"][0]["keywords"] == ["graphene", "supercapacitors", "électrodes"]
    assert doc["provenance"]["n_references_dropped"] == 1
    assert doc["provenance"]["n_records_without_keywords"] == 1


def test_numeric_identifiers_stay_whole_and_numpy_values_are_written_plainly(tmp_path):
    # A float column is what a reference id becomes once a missing value sits
    # in it, and an int64 year what a non-nullable integer column holds.
    frame = pd.DataFrame({
        "id": [85000000001],
        "title": ["A"],
        "year": np.array([2020], dtype="int64"),
        "keywords": [np.array(["Graphene"], dtype=object)],
        "references": [pd.DataFrame({"id": [1e5, np.nan], "doi": [None, None]})],
    })
    path = tmp_path / "lone.json"
    with pytest.warns(UserWarning, match="1 reference"):
        write_corpus(frame, path, "lone")
    written = _golden_form(path)
    assert '"keywords":["graphene"]' in written
    assert '"references":["scopus:100000"]' in written
    assert '"id":"scopus:85000000001"' in written
    assert '"year":2020}' in written
    assert written.endswith("}\n")


@pytest.mark.parametrize("year", [None, pd.NA, np.nan])
def test_the_provenance_block_gives_null_for_what_the_corpus_does_not_record(tmp_path, year):
    frame = pd.DataFrame({
        "id": ["10.1/A"], "title": ["A"], "year": pd.Series([year], dtype=object),
        "keywords": [[]], "references": [pd.DataFrame(columns=["id", "doi"])],
    })
    path = tmp_path / "bare.json"
    write_corpus(frame, path, "bare")
    written = _golden_form(path)
    assert '"keywords":null' in written
    assert '"query":null' in written
    assert '"retrieved_at":null' in written
    assert '"n_records_without_keywords":1' in written
    assert ('{"id":"doi:10.1/a","keywords":[],"references":[],"title":"A","year":null}'
            in written)

    # Several expressions, as a combined set records, are written as an array,
    # and a retrieval time in any zone is written in UTC.
    frame.attrs["query"] = ["TITLE(a)", "TITLE(b)"]
    frame.attrs["retrieved_at"] = datetime(2026, 10, 2, 10, 15, tzinfo=timezone(timedelta(hours=1)))
    write_corpus(frame, path, "bare")
    written = _golden_form(path)
    assert '"query":["TITLE(a)","TITLE(b)"]' in written
    assert '"retrieved_at":"2026-10-02T09:15:00Z"' in written


def test_the_writer_refuses_a_missing_id_a_malformed_corpus_or_a_record_it_cannot_key():
    frame = pd.DataFrame({
        "id": ["10.1/a"], "title": ["A"], "year": [2020], "keywords": [["x"]],
        "references": [pd.DataFrame(columns=["id", "doi"])],
    })
    for bad in (None, "", "  ", ["a", "b"], 1):
        with pytest.raises(ValueError, match="id"):
            to_theoryforge_corpus(frame, bad)
    with pytest.raises(ValueError, match="columns"):
        to_theoryforge_corpus(frame[["id", "title"]], "x")
    unkeyable = frame.assign(id=["W2741809807"])
    with pytest.raises(ValueError, match="neither"):
        to_theoryforge_corpus(unkeyable, "x")
