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
    author_only = [2, 3, 4, 5, 6, 7, 10, 11, 12, 14]
    sources = dict(zip(report.prisma["item"], report.prisma["source"], strict=True))
    assert all(sources[i] == "author" for i in author_only)
    assert all(sources[i] == "record" for i in (1, 8, 9, 13, 15))
    assert report.prisma["name"][13] == "Peer review"


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

    plan = sf.SearchPlan("graphene supercapacitor", field="TITLE-ABS-KEY")
    assert sf.scopus_search_report(records, plan=plan).view == "STANDARD"


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
