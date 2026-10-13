"""Offline tests for the search-strategy record.

The report is written for a methods section, so most of what is tested here is
what it refuses to say: no completeness without a reported total, no date
without a recorded one, no duplicate count without a merge.
"""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import scopusflow as sf


def fixture(plan=None, cells=True):
    """A harvest with every provenance attribute a live run records, assembled
    by hand because the bundled corpus carries none of them."""
    plan = plan or sf.SearchPlan("graphene supercapacitor", years=range(2015, 2025),
                                 field="TITLE-ABS-KEY", partition="year")
    records = sf.example_records()
    records.attrs["plan"] = plan
    records.attrs["retrieved_at"] = datetime(2026, 7, 22, 9, 15, tzinfo=timezone.utc)
    records.attrs["scopusflow_version"] = "0.3.0"
    records.attrs["paging"] = "offset"
    if cells:
        per_year = records.groupby("year").size()
        records.attrs["cell_totals"] = pd.DataFrame({
            "cell": list(range(1, len(per_year) + 1)),
            "date": [str(y) for y in per_year.index],
            "n_records": list(per_year.values),
            "reported_total": list(per_year.values),
        })
    return records


def test_report_carries_the_recorded_facts():
    report = sf.scopus_search_report(fixture())
    assert report.query == "graphene supercapacitor"
    assert report.expression == ["TITLE-ABS-KEY(graphene supercapacitor)"]
    assert report.field == "TITLE-ABS-KEY"
    assert report.view == "STANDARD"
    assert report.page_size == 200
    assert report.paging == "offset"
    assert report.partition == "year"
    assert report.n_cells == 10
    assert report.years == "2015 to 2024"
    assert report.n_records == 138
    assert report.n_with_doi == 127
    assert report.reported_total == 138
    assert len(report.cells) == 10


def test_report_and_paragraph_state_the_recorded_numbers():
    report = sf.scopus_search_report(fixture())
    text = report.format(style="report")
    assert "Date searched: 2026-07-22 09:15:00 UTC" in text
    assert "Records retrieved: 138" in text
    assert "Records carrying a DOI: 127 of 138" in text
    assert "every record the API reported as matching was retrieved" in text
    assert str(report) == text

    para = report.format(style="paragraph")
    assert "on 22 July 2026" in para
    assert "retrieved 138 records" in para
    assert "127 carry a DOI" in para
    assert "scopusflow 0.3.0" in para


def test_unrun_plan_claims_nothing_about_a_harvest():
    plan = sf.SearchPlan("x", years=range(2019, 2022), partition="year")
    report = sf.scopus_search_report(plan)
    assert report.n_records is None
    assert report.searched_at is None
    assert report.reported_total is None
    text = report.format(style="report")
    assert "Records retrieved: none, this plan has not been run" in text
    assert "Completeness: every" not in text
    assert "The search described here has not been run." in report.format(style="paragraph")


def test_absent_retrieval_time_is_never_replaced_by_the_current_time():
    records = fixture()
    del records.attrs["retrieved_at"]
    report = sf.scopus_search_report(records)
    assert report.searched_at is None
    text = report.format(style="report")
    assert ("Date searched: unrecorded, this set does not carry the time it was "
            "retrieved") in text
    assert datetime.now(timezone.utc).strftime("%Y-%m-%d") not in text
    assert "on a date this record does not carry" in report.format(style="paragraph")
    assert report.prisma["source"][12] == "author"


def test_unrecorded_total_means_no_completeness_figure():
    report = sf.scopus_search_report(fixture(cells=False))
    assert report.reported_total is None
    text = report.format(style="report")
    assert ("Records reported as matching: unrecorded, the API's own count did not "
            "travel with this set") in text
    assert ("Completeness: unrecorded, since the number of records the API reported "
            "as matching is not known") in text
    assert "cannot be shown to be complete" in report.format(style="paragraph")


def test_a_total_for_only_some_cells_gives_no_overall_figure():
    records = fixture()
    totals = records.attrs["cell_totals"].copy()
    totals.loc[[1, 4], "reported_total"] = None
    records.attrs["cell_totals"] = totals
    report = sf.scopus_search_report(records)
    assert report.reported_total is None
    assert report.cells_reported == 8
    assert ("unrecorded for 2 of 10 cells, so no overall figure is given"
            in report.format(style="report"))
    assert "missing for 2 of the 10 cells" in report.format(style="paragraph")


def test_a_shortfall_is_reported_as_incomplete():
    records = fixture()
    totals = records.attrs["cell_totals"].copy()
    totals.loc[2, "reported_total"] = totals.loc[2, "reported_total"] + 20
    records.attrs["cell_totals"] = totals
    report = sf.scopus_search_report(records)
    assert report.reported_total == 158
    text = report.format(style="report")
    assert "138 of the 158 records reported as matching were retrieved" in text
    assert "(2017): 10 retrieved, 30 reported, incomplete" in text
    assert "so the harvest is incomplete" in report.format(style="paragraph")


def test_duplicates_are_reported_only_where_a_merge_recorded_them():
    records = fixture()
    report = sf.scopus_search_report(records)
    assert report.duplicates_removed is None
    assert ("Duplicates removed: unrecorded, no de-duplication step was recorded "
            "for this set") in report.format(style="report")
    assert report.prisma["source"][15] == "author"

    records.attrs["combined"] = {"n_in": 149, "n_out": 138, "n_removed": 11,
                                 "deduplicated": True}
    deduped = sf.scopus_search_report(records)
    assert deduped.duplicates_removed == 11
    assert deduped.prisma["source"][15] == "record"
    assert "Duplicates removed: 11 of 149 combined records" in deduped.format()

    records.attrs["combined"] = {"n_in": 276, "n_out": 276, "n_removed": 0,
                                 "deduplicated": False}
    plain = sf.scopus_search_report(records)
    assert plain.prisma["source"][15] == "author"
    assert "none, the sets were combined without de-duplication" in plain.format()


def test_prisma_2020_identification_counts_reconcile_with_the_set():
    # The flow diagram subtracts the duplicates removed from the records
    # identified to reach the records screened, so identification is counted
    # before the merge dropped anything: 149 less 11 is the 138 rows held.
    records = fixture()
    records.attrs["combined"] = {"n_in": 149, "n_out": 138, "n_removed": 11,
                                 "deduplicated": True}
    text = sf.scopus_search_report(records).format(style="report")
    assert "Records identified from Scopus: 149" in text
    assert "Duplicate records removed before screening: 11" in text

    # With no merge recorded there is nothing to subtract, and the rows
    # retrieved are the records identified.
    plain = sf.scopus_search_report(fixture()).format(style="report")
    assert "Records identified from Scopus: 138" in plain


def test_a_plan_that_has_not_run_is_described_in_the_present():
    para = sf.scopus_search_report(
        sf.SearchPlan("x", years=range(2019, 2022), partition="year")
    ).format(style="paragraph")
    assert "The search expression is x, limited to publication years 2019 to 2021." in para
    assert "It would be partitioned into 3 cells" in para
    assert "The search expression was" not in para

    # No line may imply a set exists to have carried something.
    bare = sf.scopus_search_report(sf.SearchPlan("x"))
    assert "The search expression is x, with no year limit." in bare.format(
        style="paragraph")
    text = bare.format(style="report")
    assert "Date searched: unrecorded, this plan has not been run" in text
    assert "the time it was retrieved" not in text
    assert "which this set does not carry" not in text

    # A harvest that simply lost its stamp still says so as a set.
    records = fixture()
    del records.attrs["retrieved_at"]
    run = sf.scopus_search_report(records).format(style="report")
    assert ("Date searched: unrecorded, this set does not carry the time it was "
            "retrieved") in run


def test_prisma_map_never_claims_an_item_the_package_cannot_know():
    report = sf.scopus_search_report(fixture())
    assert len(report.prisma) == 16
    assert list(report.prisma["item"]) == list(range(1, 17))
    author_only = [3, 4, 5, 6, 7, 10, 11, 12, 14]
    sources = dict(zip(report.prisma["item"], report.prisma["source"], strict=True))
    assert all(sources[i] == "author" for i in author_only)
    assert all(sources[i] == "record" for i in (1, 2, 8, 9, 13, 15))
    assert report.prisma["name"][13] == "Peer review"


def test_item_2_says_scopus_was_searched_on_its_own():
    # PRISMA-S item 2 asks which databases were searched together on one
    # platform, as Ovid searches several at once. Scopus is searched alone, so
    # the record can say so. Other databases a review searched are named under
    # item 1, by the author.
    report = sf.scopus_search_report(fixture())
    assert report.prisma["source"][1] == "record"
    assert report.prisma["note"][1] == (
        "Scopus was searched on its own, not as one of several databases "
        "searched together on one platform.")
    # A plan not yet run is described in the present, as the paragraph is.
    unrun = sf.scopus_search_report(sf.SearchPlan("x"))
    assert unrun.prisma["source"][1] == "record"
    assert unrun.prisma["note"][1] == (
        "Scopus is searched on its own, not as one of several databases "
        "searched together on one platform.")


def test_records_without_a_plan_report_what_they_hold_and_no_more():
    records = sf.example_records()
    records.attrs["total_results"] = 200
    report = sf.scopus_search_report(records)
    assert report.view is None
    assert report.partition is None
    assert report.expression == ["graphene supercapacitor"]
    assert report.reported_total == 200
    assert report.snippet is None
    text = report.format(style="report")
    assert "View: unrecorded" in text
    assert "Field tag: unrecorded" in text
    assert "no reproduction snippet can be written" in report.format(style="markdown")

    # The year limit is unrecorded, which is not the same as there being none.
    assert "  1 (year limit unrecorded): 138 retrieved, 200 reported, incomplete" in text
    assert "no year limit" not in text
    assert "| 1 | year limit unrecorded | 138 | 200 | no |" in report.format(
        style="markdown")

    # The expression is there, but nothing records the field tag and the year
    # limit it was sent with, so the full strategy is the author's to give.
    assert report.prisma["source"][7] == "author"
    assert report.prisma["note"][7] == (
        "The search expression is recorded, but no plan records the limits it "
        "was sent with.")

    plan = sf.SearchPlan("graphene supercapacitor", field="TITLE-ABS-KEY")
    with_plan = sf.scopus_search_report(records, plan=plan)
    assert with_plan.view == "STANDARD"
    assert with_plan.prisma["source"][7] == "record"

    # A one-cell plan describes the one search the set came from, so the set's
    # own counts stay with it, as they do in the R twin.
    assert list(with_plan.cells["n_records"]) == [138]
    assert list(with_plan.cells["reported_total"]) == [200]
    assert with_plan.reported_total == 200
    assert ("  1 (no year limit): 138 retrieved, 200 reported, incomplete"
            in with_plan.format(style="report"))

    # A partitioned plan cannot say which cell the count belongs to, so its
    # cells stay unrecorded.
    by_year = sf.SearchPlan("graphene supercapacitor", years=[2015, 2016],
                            partition="year")
    split = sf.scopus_search_report(records, plan=by_year)
    assert split.cells["n_records"].isna().all()
    assert split.reported_total is None


def test_a_plan_that_sets_no_year_limit_still_says_there_is_none():
    text = sf.scopus_search_report(sf.SearchPlan("x")).format(style="report")
    assert "  1 (no year limit): retrieved records unrecorded" in text
    assert "year limit unrecorded" not in text


def test_a_harvest_run_over_several_days_is_dated_from_its_first_search_to_its_last():
    # PRISMA-S item 13 asks for the date of the last search. A resumed harvest
    # or a merged set spans days, and its earliest stamp alone hid when it was
    # last searched.
    records = fixture()
    records.attrs["retrieved_at"] = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
    records.attrs["retrieved_until"] = "2026-07-27T16:30:00+00:00"
    report = sf.scopus_search_report(records)
    assert report.searched_at == datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
    assert report.searched_until == datetime(2026, 7, 27, 16, 30, tzinfo=timezone.utc)
    assert ("Date searched: 2026-07-20 09:00:00 UTC to 2026-07-27 16:30:00 UTC\n"
            in report.format(style="report"))
    assert report.prisma["source"][12] == "record"
    assert report.prisma["note"][12] == (
        "Last searched on 2026-07-27 16:30:00 UTC; the records were retrieved "
        "between 2026-07-20 09:00:00 UTC and 2026-07-27 16:30:00 UTC.")
    assert ("searched in Scopus, on the Elsevier Scopus Search API, between "
            "20 July 2026 and 27 July 2026." in report.format(style="paragraph"))


def test_stamps_on_one_utc_day_give_the_single_date_they_always_gave():
    records = fixture()
    records.attrs["retrieved_until"] = datetime(2026, 7, 22, 18, 45, tzinfo=timezone.utc)
    report = sf.scopus_search_report(records)
    assert "Date searched: 2026-07-22 09:15:00 UTC\n" in report.format(style="report")
    assert report.prisma["note"][12] == "2026-07-22 09:15:00 UTC."
    assert "Search API, on 22 July 2026." in report.format(style="paragraph")

    # The day is the UTC day, so an hour either side of midnight is two days.
    records.attrs["retrieved_at"] = datetime(2026, 7, 22, 23, 30, tzinfo=timezone.utc)
    records.attrs["retrieved_until"] = datetime(2026, 7, 23, 0, 30, tzinfo=timezone.utc)
    assert ("Date searched: 2026-07-22 23:30:00 UTC to 2026-07-23 00:30:00 UTC"
            in sf.scopus_search_report(records).format(style="report"))

    # A latest stamp recorded before the earliest is no span at all.
    records.attrs["retrieved_until"] = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert (sf.scopus_search_report(records).searched_until
            == records.attrs["retrieved_at"])


def test_non_contiguous_year_cells_are_listed_not_shown_as_one_span():
    # Three year cells for 2015, 2020 and 2025 searched three years. Written up
    # as 2015 to 2025 they claimed eight more.
    report = sf.scopus_search_report(
        sf.SearchPlan("x", years=[2015, 2020, 2025], partition="year"))
    assert report.years == "2015, 2020 and 2025"
    text = report.format(style="report")
    assert "Years: 2015, 2020 and 2025\n" in text
    assert "9 Limits and restrictions. Publication years 2015, 2020 and 2025." in text
    assert ("limited to publication years 2015, 2020 and 2025."
            in report.format(style="paragraph"))

    def years_of(**kwargs):
        return sf.scopus_search_report(sf.SearchPlan("x", **kwargs)).years

    # A run of three or more years within the list reads as a span.
    assert years_of(years=[*range(2010, 2014), *range(2020, 2023)],
                    partition="year") == "2010 to 2013 and 2020 to 2022"
    assert years_of(years=[2015, 2016, 2020], partition="year") == "2015, 2016 and 2020"
    assert years_of(years=[2015, *range(2017, 2021)],
                    partition="year") == "2015 and 2017 to 2020"
    # Contiguous cells stay one span. A single cell sends one range from the
    # earliest year to the latest, which is what the record states for it.
    assert years_of(years=range(2015, 2026), partition="year") == "2015 to 2025"
    assert years_of(years=[2015, 2020, 2025]) == "2015 to 2025"
    assert years_of(years=[2019], partition="year") == "2019"


def test_the_reproduction_snippet_rebuilds_the_plan_it_describes(monkeypatch):
    # The fetch is masked: the claim under test is that the plan comes back
    # equal, and running the harvest would need a key and spend quota.
    monkeypatch.setattr(sf, "fetch_plan", lambda plan, **kwargs: plan)
    grid = [
        sf.SearchPlan("a b", years=range(2015, 2021), field="TITLE-ABS-KEY",
                      partition="year"),
        sf.SearchPlan("a b", years=[2015, 2017, 2021], partition="year"),
        sf.SearchPlan("a b", years=range(2015, 2021), partition="none"),
        sf.SearchPlan("a b", partition="none"),
        sf.SearchPlan("a b", years=[2019]),
        sf.SearchPlan('a "quoted" query', years=range(2015, 2017), view="COMPLETE"),
        sf.SearchPlan("a b", view="COMPLETE", partition="none"),
        sf.SearchPlan("a b", years=range(2015, 2017), page_size=37, partition="year"),
        # Years typed out of order, or twice, describe the same search. The
        # snippet renders them canonically, and the plan stores them the same
        # way, so the rebuilt plan compares equal rather than differing on the
        # order they happened to be written in.
        sf.SearchPlan("a b", years=[2020, 2019], partition="year"),
        sf.SearchPlan("a b", years=[2024, 2015, 2019, 2016, 2015], partition="none"),
    ]
    for plan in grid:
        snippet = sf.scopus_search_report(plan).snippet
        namespace: dict = {}
        exec(snippet, namespace)  # noqa: S102 - running the snippet is the test
        assert namespace["plan"] == plan
        assert namespace["records"] == plan


def test_the_snippet_pages_the_search_as_the_records_were_paged(monkeypatch):
    # fetch_plan() pages by cursor unless told otherwise, so only cursor=False
    # reproduces a harvest paged by offset.
    calls = []
    monkeypatch.setattr(sf, "fetch_plan",
                        lambda plan, **kwargs: calls.append(kwargs) or plan)
    plan = sf.SearchPlan("a b", years=range(2015, 2017), partition="year")
    records = fixture(plan, cells=False)
    snippet = sf.scopus_search_report(records).snippet
    assert snippet.endswith("\nrecords = sf.fetch_plan(plan, cursor=False)")
    namespace: dict = {}
    exec(snippet, namespace)  # noqa: S102 - running the snippet is the test
    assert namespace["plan"] == plan
    assert calls == [{"cursor": False}]

    # A harvest paged by cursor, one that does not record its paging and a
    # plan not yet run all take the default.
    records.attrs["paging"] = "cursor"
    cursor_paged = sf.scopus_search_report(records).snippet
    del records.attrs["paging"]
    unrecorded = sf.scopus_search_report(records).snippet
    for snippet in (cursor_paged, unrecorded, sf.scopus_search_report(plan).snippet):
        assert snippet.endswith("\nrecords = sf.fetch_plan(plan)")


def test_file_writes_markdown_and_only_when_supplied(tmp_path):
    report = sf.scopus_search_report(fixture())
    path = tmp_path / "record.md"
    assert not path.exists()
    out = sf.scopus_search_report(fixture(), file=str(path))
    assert path.exists()
    assert isinstance(out, sf.SearchReport)
    written = path.read_text(encoding="utf-8")
    assert written == report.format(style="markdown") + "\n"
    assert written.startswith("# Search strategy record")


def test_degenerate_inputs_are_handled_rather_than_guessed_at():
    empty = pd.DataFrame(columns=sf.RECORD_COLUMNS)
    empty.attrs["plan"] = sf.SearchPlan("x")
    report = sf.scopus_search_report(empty)
    assert report.n_records == 0
    assert report.n_with_doi == 0
    assert "Records retrieved: 0" in report.format(style="report")

    one = sf.example_records().head(1)
    one.attrs["plan"] = sf.SearchPlan("x", years=[2015])
    single = sf.scopus_search_report(one)
    assert single.years == "2015"
    assert single.n_records == 1

    none = sf.scopus_search_report(sf.SearchPlan("x"))
    assert none.years is None
    assert "Years: no year limit was applied" in none.format(style="report")


def test_the_report_refuses_what_it_cannot_describe():
    with pytest.raises(ValueError,
                       match="A search report needs a record set or a search plan."):
        sf.scopus_search_report(1)
    with pytest.raises(ValueError, match="The plan must be a search plan."):
        sf.scopus_search_report(sf.example_records(), plan="not a plan")
    with pytest.raises(ValueError, match="The file must be a single non-empty path."):
        sf.scopus_search_report(sf.example_records(), file="  ")
    with pytest.raises(ValueError, match="The file must be a single non-empty path."):
        sf.scopus_search_report(sf.example_records(), file=3)
    with pytest.raises(ValueError, match="style must be"):
        sf.scopus_search_report(sf.SearchPlan("x")).format(style="prose")


def test_page_size_travels_with_the_plan_and_is_bounded_by_the_view():
    assert sf.SearchPlan("x").page_size == 200
    assert sf.SearchPlan("x", view="COMPLETE").page_size == 25
    assert sf.SearchPlan("x", page_size=50).page_size == 50
    assert sf.SearchPlan("x", page_size=25, view="COMPLETE").cells()[0].page_size == 25
    with pytest.raises(ValueError, match="between 1 and 25 for the COMPLETE view"):
        sf.SearchPlan("x", view="COMPLETE", page_size=200)
    with pytest.raises(ValueError, match="between 1 and 200 for the STANDARD view"):
        sf.SearchPlan("x", page_size=0)
    with pytest.raises(ValueError, match="page_size must be a whole number or None."):
        sf.SearchPlan("x", page_size=2.5)
    with pytest.raises(ValueError, match="page_size must be a whole number or None."):
        sf.SearchPlan("x", page_size="200")


def test_the_record_matches_the_golden_file_both_twins_are_pinned_to():
    # golden-search-record.txt is byte-identical to the R twin's copy at
    # scopusflow/tests/testthat/golden-search-record.txt. The family advertises
    # feature parity, and this record is destined for a manuscript, so a search
    # written up in one language has to read identically in the other. Anything
    # that changes the wording has to change both files, which is the point of
    # the pin.
    records = fixture()
    records.attrs["combined"] = {"n_in": 149, "n_out": 138, "n_removed": 11,
                                 "deduplicated": True}
    report = sf.scopus_search_report(records)
    rendered = (report.format(style="report") + "\n\n"
                + report.format(style="paragraph") + "\n")
    golden = (Path(__file__).parent / "golden-search-record.txt").read_text(
        encoding="utf-8")
    assert rendered == golden


def test_the_record_reads_the_json_safe_forms_a_harvest_carries():
    # fetch_plan() stores the plan as a dict, the time as ISO 8601 text and the
    # cell totals as a list of dicts, so that a harvest can be saved. The record
    # built from those forms is the one the golden file pins.
    records = fixture()
    records.attrs["plan"] = records.attrs["plan"].to_dict()
    records.attrs["retrieved_at"] = "2026-07-22T09:15:00+00:00"
    records.attrs["cell_totals"] = records.attrs["cell_totals"].to_dict("records")
    records.attrs["combined"] = {"n_in": 149, "n_out": 138, "n_removed": 11,
                                 "deduplicated": True}
    report = sf.scopus_search_report(records)
    assert report.searched_at == datetime(2026, 7, 22, 9, 15, tzinfo=timezone.utc)
    rendered = (report.format(style="report") + "\n\n"
                + report.format(style="paragraph") + "\n")
    golden = (Path(__file__).parent / "golden-search-record.txt").read_text(
        encoding="utf-8")
    assert rendered == golden

    # A shortfall recorded in the list form is reported as one.
    records.attrs["cell_totals"][2]["reported_total"] = 30
    assert "(2017): 10 retrieved, 30 reported, incomplete" in sf.scopus_search_report(
        records).format(style="report")


def merged_fixture():
    """A baseline search and a later update of it, merged with de-duplication,
    as a review that re-runs its search a year on would hold them. Built by
    hand in the same way in the R suite, whose copy of the golden file below is
    byte-identical."""
    records = sf.example_records()
    baseline = records[(records["year"] <= 2023).fillna(False)].copy()
    baseline.attrs["retrieved_at"] = datetime(2024, 1, 10, 9, 0, tzinfo=timezone.utc)
    baseline.attrs["scopusflow_version"] = "0.3.0"
    baseline.attrs["paging"] = "offset"
    update = sf.example_records()
    update.attrs["retrieved_at"] = datetime(2025, 1, 10, 9, 0, tzinfo=timezone.utc)
    update.attrs["scopusflow_version"] = "0.4.0"
    update.attrs["paging"] = "offset"
    return sf.scopus_combine(baseline, update, dedupe=True)


def test_a_merged_sets_record_matches_the_golden_file_both_twins_are_pinned_to():
    # golden-search-record-merged.txt is byte-identical to the R twin's copy.
    # The merge keeps both retrieval dates, so the record is dated from the
    # baseline to the update, and item 13 gives the update's date as the last
    # search. No plan survives a merge, so the year limit is unrecorded and the
    # full strategy is the author's to give.
    report = sf.scopus_search_report(merged_fixture())
    rendered = (report.format(style="report") + "\n\n"
                + report.format(style="paragraph") + "\n")
    golden = (Path(__file__).parent / "golden-search-record-merged.txt").read_text(
        encoding="utf-8")
    assert rendered == golden


def _rendered(report):
    """The report and paragraph renderings, as the golden files hold them."""
    return report.format(style="report") + "\n\n" + report.format(style="paragraph") + "\n"


def _golden(name):
    return (Path(__file__).parent / name).read_text(encoding="utf-8")


def stopped_fixture(run=2):
    """A harvest stopped after ``run`` of its five year cells, as fetch_plan()
    records one when ``should_stop`` returns True, which the app's Cancel
    arranges. The attributes take the JSON-safe forms fetch_plan() writes. A
    harvest stopped before its first cell records no time and no version.
    Built the same way in the R suite, whose copy of
    golden-search-record-stopped.txt is byte-identical."""
    corpus = sf.example_records()
    years = list(range(2016, 2016 + run))
    keep = [not pd.isna(year) and int(year) in years for year in corpus["year"]]
    records = corpus[keep].copy()
    counts = [int((records["year"] == year).sum()) for year in years]
    records.attrs["plan"] = sf.SearchPlan(
        "graphene supercapacitor", years=range(2016, 2021), field="TITLE-ABS-KEY",
        partition="year").to_dict()
    if run:
        records.attrs["retrieved_at"] = "2026-07-22T09:15:00+00:00"
        records.attrs["scopusflow_version"] = "0.4.0"
    records.attrs["paging"] = "cursor"
    records.attrs["cell_totals"] = [
        {"cell": i + 1, "date": str(year), "n_records": n, "reported_total": n}
        for i, (year, n) in enumerate(zip(years, counts, strict=True))
    ]
    records.attrs["total_results"] = None
    records.attrs["stopped_early"] = True
    records.attrs["cells_planned"] = 5
    records.attrs["cells_run"] = run
    return records


def test_a_stopped_harvests_record_matches_the_golden_file_both_twins_are_pinned_to():
    assert (_rendered(sf.scopus_search_report(stopped_fixture()))
            == _golden("golden-search-record-stopped.txt"))


def test_a_stopped_harvest_says_how_many_cells_ran_and_which_years():
    # The record used to describe a harvest stopped after two of five cells as
    # fully run, each cell "retrieved records unrecorded" although two had
    # recorded their totals.
    report = sf.scopus_search_report(stopped_fixture())
    assert report.stopped_early is True
    assert report.cells_run == 2
    assert report.cells_planned == 5
    assert report.not_run == [3, 4, 5]
    assert report.years == "2016 to 2020"
    assert report.years_run == "2016 to 2017"
    text = report.format(style="report")
    assert "Years: 2016 to 2017, of 2016 to 2020 planned\n" in text
    assert ("Records reported as matching: not counted for the 3 cells not run, so "
            "no overall figure is given\n") in text
    assert "Completeness: incomplete, the harvest was stopped after 2 of 5 cells\n" in text
    assert "  1 (2016): 9 retrieved, 9 reported, complete\n" in text
    assert "  3 (2018): not run\n" in text
    assert "| 3 | 2018 | not run | not run | no |" in report.format(style="markdown")
    assert report.prisma["note"][8] == (
        "Publication years 2016 to 2020. Of the 5 cells planned, 2 were retrieved "
        "before the harvest was stopped (2016 to 2017). scopusflow applies no "
        "document type, language or subject area limit of its own.")
    assert report.prisma["note"][14] == (
        "19 records retrieved from Scopus before the harvest was stopped after 2 of "
        "5 cells.")
    para = report.format(style="paragraph")
    assert "one per year, each to be retrieved through the STANDARD view" in para
    assert "each retrieved through" not in para
    assert ("Of the 5 cells planned, 2 were retrieved before the harvest was stopped "
            "(2016 to 2017), so the harvest is incomplete. The search retrieved 19 "
            "records.") in para


def test_a_harvest_stopped_before_its_first_cell_claims_no_search():
    report = sf.scopus_search_report(stopped_fixture(run=0))
    assert report.not_run == [1, 2, 3, 4, 5]
    text = report.format(style="report")
    assert "Years: none, of 2016 to 2020 planned\n" in text
    assert "Date searched: none, the harvest was stopped before its first cell\n" in text
    assert "Completeness: incomplete, the harvest was stopped after 0 of 5 cells\n" in text
    assert "  1 (2016): not run\n" in text
    assert report.prisma["note"][8] == (
        "Publication years 2016 to 2020. Of the 5 cells planned, none was retrieved "
        "before the harvest was stopped. scopusflow applies no document type, "
        "language or subject area limit of its own.")
    para = report.format(style="paragraph")
    assert para.startswith(
        "The literature was to be searched in Scopus, on the Elsevier Scopus Search API.")
    assert "The literature was searched" not in para
    assert ("Of the 5 cells planned, none was retrieved before the harvest was "
            "stopped, so the harvest is incomplete.") in para


def test_a_cap_is_not_said_to_have_held_on_a_harvest_stopped_before_its_first_cell():
    # No cell ran, so nothing was retrieved under the cap, and "did not bind"
    # would describe a retrieval that never happened.
    records = stopped_fixture(run=0)
    records.attrs["max_results"] = 50
    report = sf.scopus_search_report(records)
    assert report.prisma["note"][8] == (
        "Publication years 2016 to 2020. A cap of 50 records per cell was set. Of the "
        "5 cells planned, none was retrieved before the harvest was stopped. scopusflow "
        "applies no document type, language or subject area limit of its own.")
    for style in ("report", "paragraph", "markdown"):
        assert "did not bind" not in report.format(style=style)
    assert ("The search retrieved 0 records. A cap of 50 records per cell was set."
            in report.format(style="paragraph"))


def test_a_stopped_set_without_its_plan_still_says_it_was_stopped():
    records = stopped_fixture()
    del records.attrs["plan"]
    report = sf.scopus_search_report(records)
    assert ("Completeness: incomplete, the harvest was stopped after 2 of 5 cells\n"
            in report.format(style="report"))
    assert ("Of the 5 cells planned, 2 were retrieved before the harvest was stopped, "
            "so the harvest is incomplete.") in report.format(style="paragraph")


def test_a_plan_that_is_not_the_one_a_stopped_harvest_ran_leaves_its_cells_unrecorded():
    # Three cells where the harvest planned five: the recorded counts cannot be
    # placed on this plan's cells, so none is marked as run or not run. A
    # mismatched plan passed by hand has always been treated that way.
    other = sf.SearchPlan("graphene supercapacitor", years=range(2016, 2019),
                          partition="year")
    report = sf.scopus_search_report(stopped_fixture(), plan=other)
    assert report.cells["n_records"].isna().all()
    assert report.not_run == []
    text = report.format(style="report")
    assert "  1 (2016): retrieved records unrecorded\n" in text
    assert "not run\n" not in text
    assert "Years: 2016 to 2018\n" in text
    assert "Completeness: incomplete, the harvest was stopped after 2 of 5 cells\n" in text


def capped_fixture(cap=200, n_records=(200, 200), reported=(1532, 1532)):
    """A plan harvest stopped by a cap of 200 records per cell, as the R twin's
    scopus_fetch_plan(max_results = 200) records one: two year cells for which
    the API reported 1,532 records each. fetch_plan() takes no cap, so this
    branch is dormant here and the attribute is set by hand. The rows are the
    bundled corpus in order, recycled to the 400 the cells held, since the
    record reads only how many rows there are and how many carry a DOI. Built
    the same way in the R suite, whose copy of golden-search-record-capped.txt
    is byte-identical."""
    corpus = sf.example_records()
    rows = [i % len(corpus) for i in range(sum(n_records))]
    records = corpus.iloc[rows].reset_index(drop=True)
    records.attrs["plan"] = sf.SearchPlan(
        "graphene supercapacitor", years=range(2023, 2025), field="TITLE-ABS-KEY",
        partition="year")
    records.attrs["retrieved_at"] = datetime(2026, 7, 22, 9, 15, tzinfo=timezone.utc)
    records.attrs["scopusflow_version"] = "0.4.0"
    records.attrs["paging"] = "offset"
    records.attrs["cell_totals"] = pd.DataFrame({
        "cell": [1, 2], "date": ["2023", "2024"], "n_records": list(n_records),
        "reported_total": list(reported),
    })
    records.attrs["max_results"] = cap
    return records


def test_a_capped_harvests_record_matches_the_golden_file_both_twins_are_pinned_to():
    assert (_rendered(sf.scopus_search_report(capped_fixture()))
            == _golden("golden-search-record-capped.txt"))


def test_a_cell_stopped_at_the_cap_says_so_and_the_record_names_the_cap():
    report = sf.scopus_search_report(capped_fixture())
    assert report.max_results == 200
    text = report.format(style="report")
    assert ("  1 (2023): 200 retrieved, 1,532 reported, stopped at the requested cap "
            "of 200\n") in text
    assert ("Completeness: 400 of the 3,064 records reported as matching were "
            "retrieved, a shortfall due to the requested cap of 200 records per "
            "cell\n") in text
    assert report.prisma["source"][8] == "record"
    assert report.prisma["note"][8] == (
        "Publication years 2023 to 2024. Records per cell were capped at 200. "
        "scopusflow applies no document type, language or subject area limit of its "
        "own.")
    assert "| 1 | 2023 | 200 | 1,532 | capped at 200 |" in report.format(style="markdown")
    assert ("so the harvest is incomplete. Records per cell were capped at 200, which "
            "accounts for the whole shortfall.") in report.format(style="paragraph")


def test_a_cap_that_never_bound_is_named_and_nothing_is_called_capped():
    report = sf.scopus_search_report(
        capped_fixture(cap=2000, n_records=(150, 120), reported=(150, 120)))
    text = report.format(style="report")
    assert "  1 (2023): 150 retrieved, 150 reported, complete\n" in text
    assert "Completeness: every record the API reported as matching was retrieved\n" in text
    assert "stopped at" not in text
    assert report.prisma["note"][8] == (
        "Publication years 2023 to 2024. A cap of 2,000 records per cell was set and "
        "did not bind. scopusflow applies no document type, language or subject area "
        "limit of its own.")
    assert ("A cap of 2,000 records per cell was set and did not bind."
            in report.format(style="paragraph"))


def test_a_shortfall_the_cap_explains_only_in_part_counts_the_capped_cells():
    report = sf.scopus_search_report(
        capped_fixture(n_records=(200, 150), reported=(1532, 160)))
    text = report.format(style="report")
    assert "  2 (2024): 150 retrieved, 160 reported, incomplete\n" in text
    assert ("Completeness: 350 of the 1,692 records reported as matching were "
            "retrieved, and 1 of 2 cells stopped at the requested cap of 200\n") in text
    assert ("Records per cell were capped at 200, and 1 of 2 cells stopped at that cap."
            in report.format(style="paragraph"))


def test_a_cell_at_the_cap_without_a_reported_total_still_stopped_at_the_cap():
    report = sf.scopus_search_report(capped_fixture(reported=(None, None)))
    text = report.format(style="report")
    assert ("  1 (2023): 200 retrieved, reported total unrecorded, stopped at the "
            "requested cap of 200\n") in text
    assert ("Completeness: unrecorded, since the number of records the API reported "
            "as matching is not known, and 2 of 2 cells stopped at the requested cap "
            "of 200\n") in text


def test_a_single_search_stopped_at_its_cap_is_written_up_as_capped():
    records = sf.example_records().head(25)
    records.attrs["plan"] = sf.SearchPlan("graphene supercapacitor", field="TITLE-ABS-KEY")
    records.attrs["total_results"] = 500
    records.attrs["max_results"] = 25
    report = sf.scopus_search_report(records)
    assert ("  1 (no year limit): 25 retrieved, 500 reported, stopped at the requested "
            "cap of 25\n") in report.format(style="report")
    assert report.prisma["note"][8] == (
        "No year limit was applied. Records per cell were capped at 25. scopusflow "
        "applies no document type, language or subject area limit of its own.")


def test_the_snippet_leaves_out_a_cap_fetch_plan_cannot_take():
    # fetch_plan() has no max_results, so a cap recorded by hand cannot be
    # passed to it, and the snippet stays runnable.
    snippet = sf.scopus_search_report(capped_fixture()).snippet
    assert snippet.endswith("\nrecords = sf.fetch_plan(plan, cursor=False)")
    assert "max_results" not in snippet


def test_a_harvest_neither_capped_nor_stopped_reads_as_it_always_has():
    # The golden test above pins the whole record. The new attributes, absent,
    # leave nothing behind in any rendering.
    report = sf.scopus_search_report(fixture())
    assert report.max_results is None
    assert report.stopped_early is False
    assert report.not_run == []
    for style in ("report", "paragraph", "markdown"):
        text = report.format(style=style)
        assert "capped" not in text and "cap of" not in text
        assert "stopped" not in text
        assert "not run" not in text
