"""Offline tests for merging record sets."""

from datetime import datetime, timezone

import pandas as pd
import pytest

import scopusflow as sf


def test_combine_binds_and_renumbers_entries():
    out = sf.scopus_combine(sf.example_records(), sf.example_records())
    assert len(out) == 276
    assert list(out["entry_number"]) == list(range(1, 277))


def test_combine_deduplicates_by_id_then_doi():
    out = sf.scopus_combine(sf.example_records(), sf.example_records(), dedupe=True)
    # These records carry no Scopus identifier, so de-duplication falls back to
    # the DOI: the 127 that have one collapse to a single copy each, and the 11
    # that have neither key are all kept. The R twin returns the same 149.
    assert len(out) == 149
    assert list(out["entry_number"]) == list(range(1, 150))


def test_combine_records_what_went_in_and_what_was_removed():
    # The count only exists at the moment of the merge, and PRISMA-S asks for it
    # (item 16), so a report has to be able to read it back.
    merged = sf.scopus_combine(sf.example_records(), sf.example_records(), dedupe=True)
    recorded = merged.attrs["combined"]
    assert recorded["n_in"] == 276
    assert recorded["n_out"] == 149
    assert recorded["n_removed"] == 127
    assert recorded["deduplicated"] is True

    # Without de-duplication the merge is still recorded, so a report can tell
    # "no duplicates were removed" from "nobody looked".
    plain = sf.scopus_combine(sf.example_records(), sf.example_records())
    assert plain.attrs["combined"]["n_removed"] == 0
    assert plain.attrs["combined"]["deduplicated"] is False


def test_combine_accepts_a_list_and_refuses_anything_else():
    out = sf.scopus_combine([sf.example_records(), sf.example_records()])
    assert len(out) == 276
    with pytest.raises(ValueError,
                       match="All inputs to scopus_combine\\(\\) must be record frames."):
        sf.scopus_combine(sf.example_records(), "not a frame")
    with pytest.raises(ValueError):
        sf.scopus_combine()


def test_combine_handles_degenerate_inputs():
    empty = pd.DataFrame(columns=sf.RECORD_COLUMNS)
    out = sf.scopus_combine(empty, empty, dedupe=True)
    assert len(out) == 0
    assert out.attrs["combined"]["n_in"] == 0

    one = sf.example_records().head(1)
    assert len(sf.scopus_combine(one, one, dedupe=True)) == 1

    # Records with neither an identifier nor a DOI cannot be matched, so both
    # copies survive, as they do in the R twin.
    keyless = sf.example_records()[lambda d: d["doi"].isna()].head(2)
    assert len(sf.scopus_combine(keyless, keyless, dedupe=True)) == 4

    # A DOI differing only in case is one record.
    upper = one.copy()
    upper["doi"] = upper["doi"].str.upper()
    assert len(sf.scopus_combine(one, upper, dedupe=True)) == 1


def test_a_merge_carries_no_attribute_describing_a_single_retrieval():
    """Two harvests each carry a ``cell_totals`` frame, and ``concat`` used to
    compare the inputs' attrs to decide whether to hand them on, which raised
    "The truth value of a DataFrame is ambiguous". Where the comparison did
    succeed the result was worse: the union inherited one harvest's plan and
    reported total, and the search record then called it complete against a
    figure belonging to a part of it."""
    def harvest():
        records = sf.example_records()
        records.attrs["plan"] = sf.SearchPlan("g", years=range(2015, 2017),
                                              partition="year")
        records.attrs["cell_totals"] = pd.DataFrame({
            "cell": [1, 2], "date": ["2015", "2016"],
            "n_records": [69, 69], "reported_total": [69.0, 69.0]})
        records.attrs["total_results"] = 138
        records.attrs["retrieved_at"] = datetime(2026, 7, 22, 9, 15, tzinfo=timezone.utc)
        records.attrs["scopusflow_version"] = "0.3.0"
        return records

    # Only the merge counts and the provenance a merge does not invalidate
    # survive, as in the R twin.
    survivors = ["combined", "retrieved_at", "scopusflow_version"]
    merged = sf.scopus_combine(harvest(), harvest(), dedupe=True)
    assert sorted(merged.attrs) == survivors
    assert merged.attrs["retrieved_at"] == datetime(2026, 7, 22, 9, 15,
                                                    tzinfo=timezone.utc)
    assert merged.attrs["scopusflow_version"] == ["0.3.0"]

    # The same frame twice: attrs then compare equal, and used to propagate.
    once = harvest()
    twice = sf.scopus_combine(once, once)
    assert sorted(twice.attrs) == survivors
    assert sorted(once.attrs) == ["cell_totals", "plan", "retrieved_at",
                                  "scopusflow_version", "total_results"]

    report = sf.scopus_search_report(merged)
    assert report.reported_total is None
    assert "cannot be shown to be complete" in report.format(style="paragraph")
    assert "Records identified from Scopus: 276" in report.format(style="report")


def test_a_merge_is_dated_by_its_oldest_part():
    """A merged set is only as fresh as the oldest harvest in it, and it is the
    work of every version that built one, which is what the R twin's
    ``scopus_bind_provenance()`` records. A set whose date and software were
    dropped made the search record say both were unrecorded."""
    def harvest(day, version, paging="cursor"):
        records = sf.example_records()
        records.attrs["retrieved_at"] = datetime(2026, 7, day, 9, 15,
                                                 tzinfo=timezone.utc)
        records.attrs["scopusflow_version"] = version
        records.attrs["paging"] = paging
        return records

    merged = sf.scopus_combine(harvest(30, "0.4.0"), harvest(22, "0.3.0"))
    assert merged.attrs["retrieved_at"] == datetime(2026, 7, 22, 9, 15,
                                                    tzinfo=timezone.utc)
    assert merged.attrs["scopusflow_version"] == ["0.3.0", "0.4.0"]
    assert merged.attrs["paging"] == "cursor"

    # The R twin's record of the same two inputs reads exactly so.
    report = sf.scopus_search_report(merged)
    paragraph = report.format(style="paragraph")
    assert "on the Elsevier Scopus Search API, on 22 July 2026." in paragraph
    assert "The search was run with scopusflow 0.3.0, 0.4.0." in paragraph
    record = report.format(style="report")
    assert "Date searched: 2026-07-22 09:15:00 UTC" in record
    assert "Software: scopusflow 0.3.0, 0.4.0" in record
    assert "Paging: cursor" in record

    # A merged set merged again keeps every version once, and its own list of
    # versions is left as it was.
    again = sf.scopus_combine(merged, harvest(25, "0.4.0"), harvest(26, "0.5.0"))
    assert again.attrs["scopusflow_version"] == ["0.3.0", "0.4.0", "0.5.0"]
    assert again.attrs["retrieved_at"] == merged.attrs["retrieved_at"]
    assert merged.attrs["scopusflow_version"] == ["0.3.0", "0.4.0"]

    # An input carrying none of them takes the field with it. Dating the merge
    # by the rest could place it later than something inside it, and a mixed
    # paging mode is true of neither part.
    partial = sf.scopus_combine(harvest(22, "0.3.0"), sf.example_records())
    assert list(partial.attrs) == ["combined"]
    assert "Date searched: unrecorded" in sf.scopus_search_report(partial).format(
        style="report")

    mixed = sf.scopus_combine(harvest(22, "0.3.0"), harvest(30, "0.4.0", "offset"))
    assert "paging" not in mixed.attrs
    assert mixed.attrs["scopusflow_version"] == ["0.3.0", "0.4.0"]


def test_a_merge_keeps_the_view_only_where_every_part_records_the_same_one():
    # The view decides whether authors are first authors or author lists, so a
    # STANDARD part merged with a COMPLETE one is neither, as in the R twin.
    def harvest(view):
        records = sf.example_records()
        records.attrs["view"] = view
        return records

    same = sf.scopus_combine(harvest("STANDARD"), harvest("STANDARD"), dedupe=True)
    assert same.attrs["view"] == "STANDARD"
    assert "view" not in sf.scopus_combine(harvest("STANDARD"), harvest("COMPLETE")).attrs
    assert "view" not in sf.scopus_combine(harvest("STANDARD"), sf.example_records()).attrs
