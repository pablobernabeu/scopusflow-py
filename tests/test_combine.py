"""Offline tests for merging record sets."""

from datetime import datetime, timezone
from pathlib import Path

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
    # survive, as in the R twin. Inputs that record one time each give it as
    # both the earliest and the latest.
    survivors = ["combined", "retrieved_at", "retrieved_until", "scopusflow_version"]
    merged = sf.scopus_combine(harvest(), harvest(), dedupe=True)
    assert sorted(merged.attrs) == survivors
    assert merged.attrs["retrieved_at"] == datetime(2026, 7, 22, 9, 15,
                                                    tzinfo=timezone.utc)
    assert merged.attrs["retrieved_until"] == datetime(2026, 7, 22, 9, 15,
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
    assert merged.attrs["retrieved_until"] == datetime(2026, 7, 30, 9, 15,
                                                       tzinfo=timezone.utc)
    assert merged.attrs["scopusflow_version"] == ["0.3.0", "0.4.0"]
    assert merged.attrs["paging"] == "cursor"

    # The R twin's record of the same two inputs reads exactly so: dated from
    # the older harvest to the newer, the newer giving the last search.
    report = sf.scopus_search_report(merged)
    paragraph = report.format(style="paragraph")
    assert ("on the Elsevier Scopus Search API, between 22 July 2026 and "
            "30 July 2026." in paragraph)
    assert "The search was run with scopusflow 0.3.0, 0.4.0." in paragraph
    record = report.format(style="report")
    assert "Date searched: 2026-07-22 09:15:00 UTC to 2026-07-30 09:15:00 UTC\n" in record
    assert "13 Dates of searches. Last searched on 2026-07-30 09:15:00 UTC;" in record
    assert "Software: scopusflow 0.3.0, 0.4.0" in record
    assert "Paging: cursor" in record

    # A merged set merged again keeps every version once, and its own list of
    # versions is left as it was. Its latest time counts as that input's.
    again = sf.scopus_combine(merged, harvest(25, "0.4.0"), harvest(26, "0.5.0"))
    assert again.attrs["scopusflow_version"] == ["0.3.0", "0.4.0", "0.5.0"]
    assert again.attrs["retrieved_at"] == merged.attrs["retrieved_at"]
    assert again.attrs["retrieved_until"] == merged.attrs["retrieved_until"]
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


def test_a_merge_dates_harvests_that_carry_their_time_as_text():
    # fetch_plan() records the time as ISO 8601 text, so that a harvest can be
    # saved, and a set built by hand may carry a datetime. Either is compared
    # as the instant it names, and the earliest input's own value is kept.
    def harvest(stamp):
        records = sf.example_records()
        records.attrs["retrieved_at"] = stamp
        return records

    texts = sf.scopus_combine(harvest("2026-07-30T09:15:00+00:00"),
                              harvest("2026-07-22T09:15:00+00:00"))
    assert texts.attrs["retrieved_at"] == "2026-07-22T09:15:00+00:00"
    assert texts.attrs["retrieved_until"] == "2026-07-30T09:15:00+00:00"

    earlier = datetime(2026, 7, 21, 9, 15, tzinfo=timezone.utc)
    mixed = sf.scopus_combine(harvest("2026-07-22T09:15:00+00:00"), harvest(earlier))
    assert mixed.attrs["retrieved_at"] == earlier
    assert mixed.attrs["retrieved_until"] == "2026-07-22T09:15:00+00:00"
    later = sf.scopus_combine(harvest("2026-07-20T09:15:00+00:00"), harvest(earlier))
    assert later.attrs["retrieved_at"] == "2026-07-20T09:15:00+00:00"
    assert ("Date searched: 2026-07-20 09:15:00 UTC to 2026-07-21 09:15:00 UTC"
            in sf.scopus_search_report(later).format(style="report"))


def test_a_merge_dates_its_newest_part_by_the_latest_time_each_input_records():
    # A harvest records the latest of its cells' times as retrieved_until. A set
    # written before that attribute existed counts by the one time it carries.
    # Neither is claimed when an input carries no time at all, as before.
    def harvest(at, until=None):
        records = sf.example_records()
        records.attrs["retrieved_at"] = at
        if until is not None:
            records.attrs["retrieved_until"] = until
        return records

    resumed = harvest("2026-07-01T09:00:00+00:00", "2026-07-08T17:00:00+00:00")
    single = harvest("2026-07-05T12:00:00+00:00")
    merged = sf.scopus_combine(resumed, single)
    assert merged.attrs["retrieved_at"] == "2026-07-01T09:00:00+00:00"
    assert merged.attrs["retrieved_until"] == "2026-07-08T17:00:00+00:00"

    undated = sf.scopus_combine(resumed, sf.example_records())
    assert "retrieved_at" not in undated.attrs
    assert "retrieved_until" not in undated.attrs


def test_a_merge_compares_a_naive_time_with_an_aware_one_as_instants():
    # A time set by hand without a zone is read as local time, as the search
    # record reads it, so it merges with a harvest's time in UTC. Compared as
    # given, the two raised TypeError. They are ten days apart, so the order
    # holds whatever the local zone.
    def harvest(at):
        records = sf.example_records()
        records.attrs["retrieved_at"] = at
        return records

    naive = datetime(2026, 7, 10, 12, 0)
    aware = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    merged = sf.scopus_combine(harvest(aware), harvest(naive))
    assert merged.attrs["retrieved_at"] == naive
    assert merged.attrs["retrieved_until"] == aware
    assert "to 2026-07-20 12:00:00 UTC\n" in sf.scopus_search_report(merged).format(
        style="report")


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


def dedupe_fixture():
    """A harvest whose records carry Scopus identifiers (rows 1 to 3) and a set
    from another source that carries none (rows 4 to 10), with its DOIs spelled
    as other sources spell them. The file is byte-identical to the R twin's
    tests/testthat/fixtures/dedupe-fixture.csv, whose suite asserts the same
    results."""
    records = sf.read_records(Path(__file__).parent / "fixtures" / "dedupe-fixture.csv")
    return records.iloc[:3], records.iloc[3:]


def test_an_unidentified_record_joins_the_identified_record_with_its_doi():
    # 0.4.0 keyed an unidentified record on its DOI, lower-cased only, so the
    # prefixed and upper-case copies of 10.5555/abc.1 survived beside the
    # harvest's record of it.
    harvest, other = dedupe_fixture()
    out = sf.scopus_combine(harvest, other, dedupe=True)
    assert list(out["title"]) == [
        "First record under a shared DOI", "Second record under the shared DOI",
        "An article in the harvest", "An unidentified copy under the shared DOI",
        "An article no harvest holds", "A record with no key",
        "Another record with no key",
    ]
    assert list(out["entry_number"]) == list(range(1, 8))
    abc = out[[isinstance(d, str) and "abc.1" in d.lower() for d in out["doi"]]]
    assert list(abc["scopus_id"]) == ["85000000333"]

    recorded = out.attrs["combined"]
    assert recorded["n_removed"] == 3
    assert recorded["rule"] == "id_or_shared_doi"
    named = sf.scopus_combine(harvest, other, dedupe="id_or_shared_doi")
    assert named.attrs["combined"] == recorded


def test_records_with_different_identifiers_and_one_doi_are_kept_and_counted():
    # Scopus holds duplicate records under different identifiers, and it also
    # gives one DOI to distinct papers, so neither record is dropped by
    # default. The unidentified copy of that DOI cannot be assigned to either
    # and is kept once, apart from both.
    harvest, other = dedupe_fixture()
    out = sf.scopus_combine(harvest, other, dedupe=True)
    assert sum(isinstance(d, str) and d.lower() == "10.5555/same" for d in out["doi"]) == 2
    assert out.attrs["combined"]["doi_conflicts"] == 1


def test_id_or_doi_merges_records_with_different_identifiers_under_one_doi():
    harvest, other = dedupe_fixture()
    out = sf.scopus_combine(harvest, other, dedupe="id_or_doi")
    assert list(out["title"]) == [
        "First record under a shared DOI", "An article in the harvest",
        "An article no harvest holds", "A record with no key",
        "Another record with no key",
    ]
    recorded = out.attrs["combined"]
    assert recorded["rule"] == "id_or_doi"
    assert recorded["doi_conflicts"] == 1
    assert recorded["n_removed"] == 5


def test_id_then_doi_reproduces_the_0_4_0_rule():
    out = sf.scopus_combine(sf.example_records(), sf.example_records(),
                            dedupe="id_then_doi")
    assert len(out) == 149
    assert out.attrs["combined"]["rule"] == "id_then_doi"

    # The 0.4.0 rule compares DOIs lower-cased but not cleaned, so a resolver
    # prefix keeps two copies apart that the default rule merges.
    one = sf.example_records().head(1).assign(doi="https://doi.org/10.1/X")
    two = sf.example_records().head(1).assign(doi="10.1/x")
    assert len(sf.scopus_combine(one, two, dedupe="id_then_doi")) == 2
    assert len(sf.scopus_combine(one, two, dedupe=True)) == 1


@pytest.mark.parametrize("rule", ["id_or_shared_doi", "id_or_doi", "id_then_doi"])
def test_every_rule_merges_empty_sets_to_an_empty_set(rule):
    empty = pd.DataFrame(columns=sf.RECORD_COLUMNS)
    out = sf.scopus_combine(empty, empty, dedupe=rule)
    assert len(out) == 0
    assert out.attrs["combined"]["doi_conflicts"] == 0


def test_a_merge_without_deduplication_records_no_rule():
    plain = sf.scopus_combine(sf.example_records(), sf.example_records())
    assert plain.attrs["combined"]["rule"] is None
    assert plain.attrs["combined"]["doi_conflicts"] is None


@pytest.mark.parametrize("bad", ["both", None, 1, [True]])
def test_dedupe_refuses_anything_but_a_bool_or_the_name_of_a_rule(bad):
    records = sf.example_records().head(2)
    with pytest.raises(ValueError, match=(
            "dedupe must be True, False, 'id_or_shared_doi', 'id_or_doi' or "
            "'id_then_doi'.")):
        sf.scopus_combine(records, records, dedupe=bad)


def test_the_search_records_item_16_names_the_rule_the_merge_used():
    # The wording is asserted word for word in the R suite too.
    harvest, other = dedupe_fixture()

    def note(records):
        return sf.scopus_search_report(records).prisma["note"][15]

    merged = sf.scopus_combine(harvest, other, dedupe=True)
    assert note(merged) == (
        "3 duplicate records removed by scopus_combine() from 10 combined, "
        "matched on a shared Scopus identifier, or on a shared DOI where one "
        "record lacks an identifier. Records with different Scopus identifiers "
        "that share a DOI were kept, which leaves 1 DOI to check by hand.")
    assert note(sf.scopus_combine(harvest, other, dedupe="id_or_doi")) == (
        "5 duplicate records removed by scopus_combine() from 10 combined, "
        "matched on a shared Scopus identifier or a shared DOI, even where the "
        "identifiers differ. Records with different Scopus identifiers were "
        "merged under 1 shared DOI.")
    assert note(sf.scopus_combine(sf.example_records(), sf.example_records(),
                                  dedupe="id_then_doi")) == (
        "127 duplicate records removed by scopus_combine() from 276 combined, "
        "matched on the Scopus identifier and failing that the DOI.")

    # A set merged by 0.4.0 records no rule, and keeps the wording it had.
    merged.attrs["combined"] = {"n_in": 10, "n_out": 7, "n_removed": 3,
                                "deduplicated": True}
    assert note(merged) == (
        "3 duplicate records removed by scopus_combine() from 10 combined, "
        "matched on the Scopus identifier and failing that the DOI.")
