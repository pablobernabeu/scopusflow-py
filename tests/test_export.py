"""Offline tests for reference-manager export and result-size sizing."""

import pandas as pd
import pytest

from scopusflow.count import _count_query
from scopusflow.export import to_bibtex, to_ris


def _records():
    return pd.DataFrame({
        "scopus_id": ["85000000001", "85000000002"],
        "doi": ["10.1/a", None],
        "title": ["Cost & benefit: 50% of $x", "A record"],
        "authors": ["Smith J.;Doe A.", None],
        "year": [2021, 2020],
        "publication": ["Nature", "Science"],
        "citations": [5, 3],
    })


def test_to_bibtex_fields_escaping_and_key():
    bib = to_bibtex(_records())
    assert bib.count("@article{") == 2
    assert r"Cost \& benefit: 50\% of \$x" in bib
    assert "Smith J. and Doe A." in bib
    assert "@article{smith2021," in bib          # surname + year
    assert "@article{scopus85000000002," in bib  # no author -> scopus-id key
    assert "doi = {10.1/a}" in bib
    assert "nan" not in bib.lower()              # NaN never leaks


def test_to_ris_structure():
    ris = to_ris(_records())
    assert ris.count("TY  - JOUR") == 2
    assert ris.count("ER  - ") == 2
    assert "AU  - Smith J." in ris
    assert "AU  - Doe A." in ris
    assert "DO  - 10.1/a" in ris
    assert "PY  - 2021" in ris


def test_missing_fields_are_skipped():
    recs = pd.DataFrame({
        "scopus_id": [None], "doi": [None], "title": ["only title"],
        "authors": [None], "year": [None], "publication": [None],
    })
    bib, ris = to_bibtex(recs), to_ris(recs)
    assert "doi" not in bib
    assert "DO  - " not in ris
    assert "@article{scopusrecord," in bib
    assert "nan" not in (bib + ris).lower()


def test_export_rejects_non_dataframe():
    with pytest.raises(ValueError):
        to_bibtex(["not a frame"])


def test_colliding_keys_are_disambiguated():
    recs = pd.DataFrame({
        "scopus_id": ["1", "2"], "doi": [None, None], "title": ["A", "B"],
        "authors": ["Smith J.", "Smith K."], "year": [2021, 2021],
        "publication": ["N", "N"],
    })
    bib = to_bibtex(recs)
    assert "@article{smith2021," in bib
    assert "@article{smith2021a," in bib


def test_backslash_escaped_without_mangling():
    recs = pd.DataFrame({
        "scopus_id": ["1"], "doi": [None], "title": [r"a\b"],
        "authors": [None], "year": [None], "publication": [None],
    })
    bib = to_bibtex(recs)
    assert r"\textbackslash{}" in bib
    assert r"\textbackslash\{" not in bib


def test_pandas_NA_does_not_crash_or_leak():
    recs = pd.DataFrame({
        "scopus_id": pd.array(["85000000001", pd.NA], dtype="string"),
        "doi": pd.array(["10.1/a", pd.NA], dtype="string"),
        "title": pd.array(["Real", pd.NA], dtype="string"),
        "authors": pd.array(["Smith J.", pd.NA], dtype="string"),
        "year": pd.array([2021, pd.NA], dtype="Int64"),
        "publication": pd.array(["Nature", pd.NA], dtype="string"),
    })
    bib, ris = to_bibtex(recs), to_ris(recs)
    assert "<NA>" not in (bib + ris)
    assert "nan" not in (bib + ris).lower()
    assert bib.count("@article{") == 2


def test_newline_folded_in_ris():
    recs = pd.DataFrame({
        "scopus_id": ["1"], "doi": [None], "title": ["Line one\nLine two"],
        "authors": ["Smith J."], "year": [2021], "publication": ["N"],
    })
    ris = to_ris(recs)
    assert "TI  - Line one Line two" in ris
    assert "\nLine two" not in ris


def test_count_query_folds_field_and_years():
    assert _count_query("graphene", field="TITLE-ABS-KEY") == "TITLE-ABS-KEY(graphene)"
    assert _count_query("x", years=[2020]) == "x AND PUBYEAR IS 2020"
    assert _count_query("x", years=range(2018, 2021)) == (
        "x AND PUBYEAR AFT 2017 AND PUBYEAR BEF 2021"
    )
