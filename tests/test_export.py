"""Offline tests for reference-manager export and result-size sizing."""

import json
from pathlib import Path

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
    assert "Smith, J. and Doe, A." in bib
    assert "@article{smith2021," in bib          # surname + year
    assert "@article{scopus85000000002," in bib  # no author -> scopus-id key
    assert "doi = {10.1/a}" in bib
    assert "nan" not in bib.lower()              # NaN never leaks


def test_to_ris_structure():
    ris = to_ris(_records())
    assert ris.count("TY  - JOUR") == 2
    assert ris.count("ER  - ") == 2
    assert "AU  - Smith, J." in ris
    assert "AU  - Doe, A." in ris
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


# The name and export fixtures are shared byte for byte with the R suite, so
# both twins write the same names, titles and RIS tags.
_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _author_name_cases():
    return json.loads((_FIXTURES / "author-names.json").read_text(encoding="utf-8"))["cases"]


def _records_with_authors(authors):
    """One record per name, each name its record's only author."""
    n = len(authors)
    return pd.DataFrame({
        "scopus_id": [None] * n, "doi": [None] * n, "title": [None] * n,
        "authors": list(authors), "year": [None] * n, "publication": [None] * n,
    })


def test_ris_writes_each_name_in_the_shared_fixtures_ris_form():
    cases = _author_name_cases()
    assert len(cases) > 20
    entries = to_ris(_records_with_authors([c["input"] for c in cases])).split("\n\n")
    for case, entry in zip(cases, entries, strict=True):
        assert f"\nAU  - {case['ris']}\n" in entry, case["input"]


def test_bibtex_writes_each_name_in_the_shared_fixtures_bibtex_form():
    cases = _author_name_cases()
    entries = to_bibtex(_records_with_authors([c["input"] for c in cases])).split("\n\n")
    for case, entry in zip(cases, entries, strict=True):
        assert f"\n  author = {{{case['bibtex']}}},\n" in entry, case["input"]


def test_authors_column_and_citation_keys_are_left_as_scopus_sent_them():
    recs = _records_with_authors(["Zhang F.", "Kitchin J.R."])
    bib = to_bibtex(recs)
    assert list(recs["authors"]) == ["Zhang F.", "Kitchin J.R."]
    assert "@article{zhang," in bib
    assert "@article{kitchin," in bib


def test_bibtex_titles_protect_words_with_capitals_after_their_first_letter():
    recs = pd.DataFrame({
        "scopus_id": [None], "doi": [None], "authors": [None], "year": [None],
        "publication": [None],
        "title": ["Bayesian (DNA) and mRNA: R&D on CRISPR-Cas9 in the U.S. and 5G"],
    })
    assert (
        r"title = {Bayesian ({DNA}) and {mRNA}: {R\&D} on {CRISPR-Cas9} in the {U.S}. and {5G}},"
        in to_bibtex(recs)
    )
    # RIS titles are plain text and stay as they are.
    assert "TI  - Bayesian (DNA) and mRNA: R&D on CRISPR-Cas9 in the U.S. and 5G\n" in to_ris(recs)


def test_title_word_opening_with_an_escape_is_braced_twice():
    # BibTeX reads a brace group that opens with a backslash as a special
    # character and lower-cases the letters inside it, so ``{\#MeToo}`` would
    # still print as "#metoo".
    recs = pd.DataFrame({
        "scopus_id": [None], "doi": [None], "authors": [None], "year": [None],
        "publication": [None], "title": ["#MeToo, ~ABC and DNA in #science"],
    })
    assert (
        r"title = {{{\#MeToo}}, {{\textasciitilde{}ABC}} and {DNA} in \#science},"
        in to_bibtex(recs)
    )


def test_ris_files_the_source_under_t2_and_names_the_database_and_the_eid():
    recs = pd.DataFrame({
        "scopus_id": ["85000000201", None], "doi": [None, None],
        "title": ["A record", "No identifier"], "authors": [None, None],
        "year": [None, None], "publication": ["Journal of Mocking", None],
    })
    with_id, without_id = to_ris(recs).split("\n\n")
    assert "\nT2  - Journal of Mocking\n" in with_id
    assert "JO  - " not in with_id
    assert "\nAN  - 2-s2.0-85000000201\n" in with_id
    assert "\nDB  - Scopus\n" in with_id
    # With no identifier there is no accession number to give.
    assert "AN  - " not in without_id
    assert "\nDB  - Scopus\n" in without_id


def test_export_fixture_renders_to_the_shared_bibtex_and_ris_goldens():
    # The goldens were written by hand from the rules above, not generated by
    # either twin, and both suites compare against the same bytes. A file
    # export ends in a newline, as the R twin's writer adds one.
    recs = pd.read_csv(
        _FIXTURES / "export-fixture.csv", dtype=str, keep_default_na=False, encoding="utf-8"
    )
    assert len(recs) == 6
    for ext, render in (("bib", to_bibtex), ("ris", to_ris)):
        golden = (_FIXTURES / f"export-fixture.{ext}").read_bytes()
        assert (render(recs) + "\n").encode("utf-8") == golden, ext


def test_count_query_folds_field_and_years():
    assert _count_query("graphene", field="TITLE-ABS-KEY") == "TITLE-ABS-KEY(graphene)"
    assert _count_query("x", years=[2020]) == "x AND PUBYEAR IS 2020"
    assert _count_query("x", years=range(2018, 2021)) == (
        "x AND PUBYEAR AFT 2017 AND PUBYEAR BEF 2021"
    )


def test_count_query_brackets_a_query_whose_operators_would_swallow_the_years():
    exclusion = "TITLE-ABS-KEY(hypertension) AND NOT TITLE-ABS-KEY(pulmonary)"
    assert _count_query(exclusion, years=range(2015, 2021)) == (
        "(TITLE-ABS-KEY(hypertension) AND NOT TITLE-ABS-KEY(pulmonary)) "
        "AND PUBYEAR AFT 2014 AND PUBYEAR BEF 2021"
    )
    assert _count_query("CRISPR OR Cas9", years=[2019]) == (
        "(CRISPR OR Cas9) AND PUBYEAR IS 2019"
    )
    # The field tag's brackets already hold the OR together, and with no
    # years nothing is appended, so neither string changes.
    assert _count_query("CRISPR OR Cas9", years=[2019], field="TITLE") == (
        "TITLE(CRISPR OR Cas9) AND PUBYEAR IS 2019"
    )
    assert _count_query("CRISPR OR Cas9") == "CRISPR OR Cas9"
