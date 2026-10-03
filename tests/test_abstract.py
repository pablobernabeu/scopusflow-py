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


@pytest.mark.parametrize("eid", [None, float("nan"), pd.NA])
def test_a_missing_eid_yields_na_not_the_string_nan(eid):
    # The same guard as to_records(): a truthiness test used to stringify a
    # missing identifier into the literal "nan" and pass it downstream.
    assert pd.isna(_abstract_row({"eid": eid, "doi": "10.1/x"})["scopus_id"])


@pytest.mark.parametrize("cited", [None, "", float("nan"), pd.NA])
def test_a_missing_citation_count_yields_na_rather_than_raising(cited):
    row = _abstract_row({"eid": "2-s2.0-1", "citedby_count": cited})
    assert pd.isna(row["citations"])


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


def _reference(position):
    from pybliometrics.scopus import Reference

    return Reference(
        position=str(position), id=None, doi=None, title=f"Reference {position}",
        authors=None, authors_auid=None, authors_affiliationid=None,
        sourcetitle=None, publicationyear=None, coverDate=None,
        volume=None, issue=None, first=None, last=None, citedbycount=None,
        type="resolved", text=None, fulltext=None,
    )


def test_a_ref_list_pybliometrics_paged_is_one_document_in_n_requests():
    """pybliometrics pages REF itself (startref 1, 41, 81 for 103 references)
    and hands back the whole list, so n_requests counts documents, not pages."""
    whole = types.SimpleNamespace(
        eid="2-s2.0-1", doi="10.1/paged", title=None, description=None,
        publicationName=None, coverDate=None, citedby_count=None,
        references=[_reference(i) for i in range(1, 104)], refcount="103",
    )
    calls = []

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            calls.append(kwargs.get("view"))
            return whole

    saved = {k: sys.modules.get(k) for k in ("pybliometrics", "pybliometrics.scopus")}
    from pybliometrics.scopus import Reference
    pkg = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.AbstractRetrieval = _AbstractRetrieval
    scopus.Reference = Reference
    pkg.scopus = scopus
    sys.modules["pybliometrics"] = pkg
    sys.modules["pybliometrics.scopus"] = scopus
    try:
        import warnings as _warnings
        with _warnings.catch_warnings():
            _warnings.simplefilter("error")
            df = scopus_abstract("10.1/paged", view="REF", include=("references",))
        assert len(df.loc[0, "references"]) == 103
        assert df.attrs["n_requests"] == 1
        assert calls == ["REF"]
    finally:
        for k, mod in saved.items():
            if mod is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = mod


def test_the_documentation_does_not_blame_the_api_for_truncated_ref_lists():
    """REF is paged, and pybliometrics follows the pages. The docstrings and the
    guide called REF lists inconsistent and sometimes truncated, which was the
    R twin requesting only the first page."""
    from pathlib import Path

    from scopusflow.corpus import corpus

    guide = (
        Path(__file__).resolve().parents[1] / "docs" / "guides" / "keywords-and-references.md"
    ).read_text(encoding="utf-8")
    for name, text in [
        ("scopus_abstract", scopus_abstract.__doc__),
        ("corpus", corpus.__doc__),
        ("keywords-and-references.md", guide),
    ]:
        flat = " ".join(text.split())
        assert "truncated (paginated)" not in flat, name
        assert "sometimes-truncated" not in flat, name
        assert "pybliometrics pages" in flat, name
    assert "counts each document once" in " ".join(scopus_abstract.__doc__.split())


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


def test_a_transient_failure_is_not_checkpointed_and_a_resume_retries_it(tmp_path):
    """A failed retrieval must cost its NA row once, not forever: checkpointing
    the NA row turned a timeout or a quota refusal into permanent cached data
    that every later resume read back instead of the real record."""
    good = types.SimpleNamespace(
        eid="2-s2.0-85000000011",
        doi="10.1/flaky",
        title="Recovered paper",
        description="An abstract.",
        publicationName="Nature",
        coverDate="2022-02-01",
        citedby_count="4",
    )
    calls = {"n": 0}

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("temporarily unreachable")
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
        with pytest.warns(UserWarning, match="recording NA row"):
            first = scopus_abstract("10.1/flaky", by="doi", cache_dir=str(tmp_path))
        assert pd.isna(first.loc[0, "title"])
        assert list(tmp_path.glob("id-*.pkl")) == []   # the failure left nothing

        second = scopus_abstract("10.1/flaky", by="doi", cache_dir=str(tmp_path))
        assert second.loc[0, "title"] == "Recovered paper"
        assert calls["n"] == 2

        # The success was checkpointed, so a third run reads the cache.
        third = scopus_abstract("10.1/flaky", by="doi", cache_dir=str(tmp_path))
        assert third.loc[0, "title"] == "Recovered paper"
        assert calls["n"] == 2
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


def test_quota_reporting_tolerates_a_missing_reset_time_method():
    """An object exposing get_key_remaining_quota but not get_key_reset_time
    must still yield its real row: the unguarded reset-time lookup used to
    raise into the generic handler and record the successful retrieval as NA."""
    partial = types.SimpleNamespace(
        eid="2-s2.0-85000000012",
        doi="10.1/partial-quota",
        title="Quota paper",
        description="An abstract.",
        publicationName="Cell",
        coverDate="2020-06-01",
        citedby_count="2",
        get_key_remaining_quota=lambda: "500",
    )

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            return partial

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
        df = scopus_abstract("10.1/partial-quota", by="doi")
        assert df.loc[0, "title"] == "Quota paper"
        assert df.attrs["quota"] == {"remaining": "500", "reset": None}
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


def test_caching_writes_per_id_files_and_resume_avoids_refetch(
    tmp_path, fake_pybliometrics_rich
):
    df1 = scopus_abstract(
        "10.1/rich", view="FULL", include=("references",), cache_dir=str(tmp_path)
    )
    assert len(list(tmp_path.glob("id-*.pkl"))) == 1

    # Break AbstractRetrieval so a second, non-cached call would fail; resume
    # must still succeed by reading the cache instead of re-fetching.
    sys.modules["pybliometrics.scopus"].AbstractRetrieval = None
    df2 = scopus_abstract(
        "10.1/rich", view="FULL", include=("references",), cache_dir=str(tmp_path)
    )
    assert df2.loc[0, "doi"] == df1.loc[0, "doi"]


def test_a_half_written_abstract_checkpoint_is_retrieved_again(
    tmp_path, fake_pybliometrics_rich
):
    """Twinned with the R suite's per-identifier cache test. An interrupted run
    can leave a truncated pickle; before the atomic write and the guarded read,
    that file raised out of scopus_abstract() and blocked every later resume of
    the identifier rather than costing one retrieval."""
    scopus_abstract(
        "10.1/rich", view="FULL", include=("references",), cache_dir=str(tmp_path)
    )
    checkpoint = next(iter(tmp_path.glob("id-*.pkl")))
    checkpoint.write_bytes(checkpoint.read_bytes()[:12])   # interrupted mid-write

    with pytest.warns(UserWarning, match="could not be read back"):
        df = scopus_abstract(
            "10.1/rich", view="FULL", include=("references",), cache_dir=str(tmp_path)
        )

    # The identifier was retrieved again rather than lost, and the damaged
    # checkpoint was replaced by a readable one.
    assert df.loc[0, "doi"] == "10.1/rich"
    assert len(df) == 1
    from scopusflow.abstract import _read_abstract_checkpoint
    assert _read_abstract_checkpoint(checkpoint) is not None


def test_the_abstract_checkpoint_write_leaves_no_temporary_behind(
    tmp_path, fake_pybliometrics_rich
):
    scopus_abstract(
        "10.1/rich", view="FULL", include=("references",), cache_dir=str(tmp_path)
    )
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


# Identifiers, request counts and views, checked against a stand-in that
# records what reaches it.

def _document(ident, **fields):
    doc = types.SimpleNamespace(
        eid="2-s2.0-85000000001", doi=ident, title=f"Title of {ident}",
        description=None, publicationName=None, coverDate="2020-01-01",
        citedby_count="1",
    )
    for name, value in fields.items():
        setattr(doc, name, value)
    return doc


def _stand_in(monkeypatch, make=_document):
    """Install a stand-in pybliometrics whose AbstractRetrieval records each
    identifier it is given and returns ``make(identifier)``."""
    from pybliometrics.scopus import Reference

    calls = []

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            calls.append(ident)
            return make(ident)

    pkg = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.AbstractRetrieval = _AbstractRetrieval
    scopus.Reference = Reference
    pkg.scopus = scopus
    monkeypatch.setitem(sys.modules, "pybliometrics", pkg)
    monkeypatch.setitem(sys.modules, "pybliometrics.scopus", scopus)
    return calls


@pytest.mark.parametrize("missing", [None, pd.NA, float("nan"), "", "   "],
                         ids=["None", "NA", "nan", "empty", "blank"])
@pytest.mark.parametrize("cached", [False, True], ids=["no-cache", "cache_dir"])
def test_a_missing_identifier_is_refused_before_any_request(
    monkeypatch, tmp_path, missing, cached
):
    # None went to the API as the DOI "None" and pd.NA as "<NA>", each counted
    # as a request. With cache_dir, the batch stopped on a TypeError at the
    # first missing identifier, after spending the requests before it, and
    # did so again on every resume.
    calls = _stand_in(monkeypatch)
    kwargs = {"cache_dir": str(tmp_path / "abstracts")} if cached else {}
    with pytest.raises(ValueError, match=r"positions 1, 3\b") as caught:
        scopus_abstract(["10.1/a", missing, "10.1/c", missing], **kwargs)
    assert "corpus()" in str(caught.value)
    assert calls == []
    assert not list(tmp_path.rglob("*.pkl"))


def test_positions_in_a_series_count_from_zero_whatever_its_index(monkeypatch):
    calls = _stand_in(monkeypatch)
    ids = pd.Series(["10.1/a", None], index=[10, 11])
    with pytest.raises(ValueError, match=r"position 1\b"):
        scopus_abstract(ids)
    assert calls == []


@pytest.mark.parametrize("ids", [
    None, {"10.1/a"}, 2.5, ["10.1/a", 2.5], ["10.1/a", True], [85000000001.0],
    # A bytes object iterates as whole numbers, one per byte, which would
    # otherwise each be sent as an identifier of its own.
    b"10.1/a", bytearray(b"10.1/a"), [b"10.1/a"],
])
def test_identifiers_that_are_neither_text_nor_whole_numbers_are_refused(monkeypatch, ids):
    calls = _stand_in(monkeypatch)
    with pytest.raises(TypeError):
        scopus_abstract(ids, by="scopus_id")
    assert calls == []


def test_identifiers_reach_pybliometrics_trimmed_and_as_text(monkeypatch, tmp_path):
    # The R twin trims identifiers and strips the SCOPUS_ID: prefix that
    # Scopus' own dc:identifier carries. Whole-number Scopus IDs, as a numeric
    # column holds them, are sent as text, since pybliometrics accepts them
    # and the per-identifier checkpoint name needs a string.
    import numpy as np

    calls = _stand_in(monkeypatch)
    scopus_abstract(pd.Series([" 10.1/a ", "10.1/b\n"]), by="doi")
    assert calls == ["10.1/a", "10.1/b"]

    calls.clear()
    out = scopus_abstract(
        ["SCOPUS_ID:85000000001", 85000000002, " SCOPUS_ID:85000000003 ",
         np.int64(85000000004)],
        by="scopus_id", cache_dir=str(tmp_path),
    )
    expected = ["85000000001", "85000000002", "85000000003", "85000000004"]
    assert calls == expected
    assert len(out) == 4
    assert sorted(p.name for p in tmp_path.glob("id-*.pkl")) == sorted(
        f"id-META_ABS-plain-{ident}.pkl" for ident in expected
    )

    calls.clear()
    scopus_abstract(85000000005, by="scopus_id")
    assert calls == ["85000000005"]


@pytest.mark.parametrize("view", ["META", "META_ABS", "REF"])
def test_keywords_need_the_full_view(monkeypatch, view):
    # Only FULL carries author keywords. Under the other views the column came
    # back all NA without a word, which reads as documents without keywords.
    calls = _stand_in(monkeypatch)
    include = ("references", "keywords") if view == "REF" else ("keywords",)
    with pytest.raises(ValueError, match='view="FULL"'):
        scopus_abstract("10.1/a", view=view, include=include)
    assert calls == []


def test_n_requests_counts_the_requests_a_mixed_batch_made(monkeypatch, tmp_path):
    from scopusflow.abstract import _write_abstract_checkpoint

    requests = []

    class _Broken(types.SimpleNamespace):
        # A response that a later step fails to read: it cost one request.
        @property
        def title(self):
            raise KeyError("dc:title")

    def make(ident):
        if ident == "10.1/refused":
            requests.append(ident)
            raise RuntimeError("HTTP 404")
        if ident == "10.1/cached":
            # pybliometrics answered from its cache: no response headers were
            # kept, and the cache file predates the call.
            return _document(
                ident,
                get_key_remaining_quota=lambda: None,
                get_cache_file_mdate=lambda: "2026-01-05 10:00:00",
            )
        requests.append(ident)
        if ident == "10.1/broken":
            return _Broken(eid="2-s2.0-2", doi=ident, coverDate=None)
        return _document(ident, get_key_remaining_quota=lambda: "9000",
                         get_cache_file_mdate=lambda: "2099-01-01 00:00:00")

    calls = _stand_in(monkeypatch, make)
    _write_abstract_checkpoint(
        {"doi": "10.1/resumed", "title": "Resumed"}, tmp_path, "META_ABS", (),
        "10.1/resumed",
    )
    with pytest.warns(UserWarning) as caught:
        out = scopus_abstract(
            ["10.1/fresh", "10.1/cached", "10.1/refused", "10.1/broken", "10.1/resumed"],
            cache_dir=str(tmp_path),
        )
    assert calls == ["10.1/fresh", "10.1/cached", "10.1/refused", "10.1/broken"]
    assert out.attrs["n_requests"] == len(requests) == 3
    assert out.loc[1, "title"] == "Title of 10.1/cached"
    assert out.attrs["quota"] == {"remaining": "9000", "reset": None}
    messages = " ".join(str(w.message) for w in caught)
    assert "10.1/refused" in messages and "10.1/broken" in messages


def test_a_keyword_entry_pybliometrics_cannot_parse_leaves_the_rest_of_the_row(monkeypatch):
    # pybliometrics 4.4.1 reads each author keyword's "$" and raises KeyError
    # for an entry without one (pybliometrics issue 436). That turned the whole
    # row into NA, losing a title and references already retrieved, and
    # counted the one request twice.
    from pybliometrics.scopus import Reference

    ref = Reference(
        position="1", id="1", doi="10.1/cited", title="A cited work",
        authors=None, authors_auid=None, authors_affiliationid=None,
        sourcetitle=None, publicationyear=None, coverDate=None,
        volume=None, issue=None, first=None, last=None, citedbycount=None,
        type="resolved", text=None, fulltext=None,
    )

    class _Document436(types.SimpleNamespace):
        @property
        def authkeywords(self):
            raise KeyError("$")

    calls = _stand_in(monkeypatch, lambda ident: _Document436(
        eid="2-s2.0-85000000436", doi=ident, title="Kept title", description="Kept.",
        publicationName="Journal", coverDate="2021-01-01", citedby_count="5",
        references=[ref], refcount="1",
    ))
    with pytest.warns(UserWarning, match="10.1/kw436"):
        out = scopus_abstract("10.1/kw436", view="FULL", include=("references", "keywords"))
    assert calls == ["10.1/kw436"]
    assert out.loc[0, "title"] == "Kept title"
    assert out.loc[0, "citations"] == 5
    assert len(out.loc[0, "references"]) == 1
    assert pd.isna(out.loc[0, "authkeywords"])
    assert out.attrs["n_requests"] == 1


def test_the_docstring_matches_the_view_each_include_needs():
    flat = " ".join(scopus_abstract.__doc__.split())
    assert "Both require" not in flat
    assert '"keywords" needs the "FULL" view' in flat


# A spent quota. pybliometrics raises Scopus429Error only after rotating every
# configured key, and documents it as a depleted weekly quota, so a batch
# stops there and keeps what it holds. Twinned with the R suite's test of a
# QUOTA_EXCEEDED 429 part-way through a batch.

def _quota_stand_in(monkeypatch, runs_out_at, make=_document):
    """A stand-in pybliometrics whose AbstractRetrieval raises Scopus429Error
    from the ``runs_out_at``-th request on, with the exception module the
    defensive imports read."""
    from pybliometrics.scopus import Reference

    calls = []
    exception_mod = types.ModuleType("pybliometrics.exception")

    class _Scopus403Error(Exception):
        pass

    class _Scopus429Error(Exception):
        pass

    exception_mod.Scopus403Error = _Scopus403Error
    exception_mod.Scopus429Error = _Scopus429Error

    class _AbstractRetrieval:
        def __new__(cls, ident, **kwargs):
            calls.append(ident)
            if len(calls) >= runs_out_at:
                raise _Scopus429Error("Quota Exceeded")
            return make(ident)

    pkg = types.ModuleType("pybliometrics")
    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.AbstractRetrieval = _AbstractRetrieval
    scopus.Reference = Reference
    pkg.scopus = scopus
    pkg.exception = exception_mod
    monkeypatch.setitem(sys.modules, "pybliometrics", pkg)
    monkeypatch.setitem(sys.modules, "pybliometrics.scopus", scopus)
    monkeypatch.setitem(sys.modules, "pybliometrics.exception", exception_mod)
    return calls


def test_a_spent_quota_stops_the_batch_and_keeps_the_rows_retrieved(monkeypatch):
    # Each remaining identifier used to be tried and become an NA row with a
    # warning of its own, every one of them refused in the same way.
    import warnings as _warnings

    from scopusflow import ScopusFlowQuotaWarning

    calls = _quota_stand_in(monkeypatch, runs_out_at=2)
    ids = ["10.1/a", "10.1/b", "10.1/c", "10.1/d"]
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        out = scopus_abstract(ids)
    assert calls == ["10.1/a", "10.1/b"]
    assert out.attrs["n_requests"] == 2
    assert list(out["doi"]) == ids
    assert out.loc[0, "title"] == "Title of 10.1/a"
    assert out["title"][1:].isna().all()
    assert len(caught) == 1
    warning = caught[0]
    assert issubclass(warning.category, ScopusFlowQuotaWarning)
    assert issubclass(warning.category, UserWarning)
    message = str(warning.message)
    assert "10.1/b" in message
    assert "3 identifiers" in message


def test_after_a_spent_quota_checkpoints_are_read_and_na_rows_never_written(
    monkeypatch, tmp_path
):
    from scopusflow import ScopusFlowQuotaWarning
    from scopusflow.abstract import _write_abstract_checkpoint

    _write_abstract_checkpoint(
        {"doi": "10.1/d", "title": "Cached"}, tmp_path, "META_ABS", (), "10.1/d"
    )
    calls = _quota_stand_in(monkeypatch, runs_out_at=2)
    with pytest.warns(ScopusFlowQuotaWarning, match="2 identifiers"):
        out = scopus_abstract(["10.1/a", "10.1/b", "10.1/c", "10.1/d"], cache_dir=str(tmp_path))
    assert calls == ["10.1/a", "10.1/b"]
    assert out.loc[0, "title"] == "Title of 10.1/a"
    assert out["title"][1:3].isna().all()
    assert out.loc[3, "title"] == "Cached"
    # The row retrieved is checkpointed, the NA rows are not.
    assert sorted(p.name for p in tmp_path.glob("id-*.pkl")) == [
        "id-META_ABS-plain-10_1_a.pkl", "id-META_ABS-plain-10_1_d.pkl",
    ]


def test_the_quota_warning_gives_a_reset_time_only_when_one_was_reported(monkeypatch):
    # Scopus429Error carries no reset time. An earlier retrieval's is passed on,
    # labelled as local time since pybliometrics formats it so (the R twin
    # gives UTC); without one the warning gives Elsevier's weekly cycle.
    from scopusflow import ScopusFlowQuotaWarning

    def with_quota(ident):
        return _document(
            ident,
            get_key_remaining_quota=lambda: "1",
            get_key_reset_time=lambda: "2026-10-15 09:00:00",
        )

    _quota_stand_in(monkeypatch, runs_out_at=2, make=with_quota)
    with pytest.warns(ScopusFlowQuotaWarning) as caught:
        scopus_abstract(["10.1/a", "10.1/b"])
    assert "2026-10-15 09:00:00 (local time)" in str(caught[0].message)

    _quota_stand_in(monkeypatch, runs_out_at=1)
    with pytest.warns(ScopusFlowQuotaWarning) as caught:
        scopus_abstract(["10.1/a", "10.1/b"])
    message = str(caught[0].message)
    assert "every seven days" in message
    assert "local time" not in message


def test_the_quota_warning_is_exported_and_documented():
    import scopusflow
    from scopusflow.exceptions import ScopusFlowQuotaWarning

    assert scopusflow.ScopusFlowQuotaWarning is ScopusFlowQuotaWarning
    assert "ScopusFlowQuotaWarning" in scopusflow.__all__
    flat = " ".join(scopus_abstract.__doc__.split())
    assert "ScopusFlowQuotaWarning" in flat
