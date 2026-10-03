"""Offline tests for saving a record set and reading it back.

A harvest is a baseline only if it can be kept. ``fetch_plan()`` used to attach
a ``SearchPlan``, a ``datetime`` and a DataFrame as attributes, so
``DataFrame.to_parquet`` raised on every real harvest (pandas 2.1 and later
write ``attrs`` as JSON), and ``merge``, ``groupby(...).apply`` and ``concat``
raised "The truth value of a DataFrame is ambiguous" when pandas compared the
inputs' attributes. A CSV round trip lost every attribute and turned
``scopus_id`` into a number, after which a de-duplicating merge matched nothing.
"""

import json
import sys
import types
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import scopusflow as sf

#: The records each year cell returns. The 2020 cell holds one record with no
#: Scopus identifier, so a CSV read without a schema infers float64 for the
#: whole column and "85000000003" comes back as 85000000003.0.
_ROWS = {
    "2019": [
        {"eid": "2-s2.0-85000000001", "doi": "10.1/a", "title": "A",
         "creator": "Smith J.", "coverDate": "2019-05-01",
         "publicationName": "Journal", "citedby_count": "3"},
        {"eid": "2-s2.0-85000000002", "doi": "10.1/b", "title": "B",
         "creator": "Doe A.", "coverDate": "2019-07-01",
         "publicationName": "Journal", "citedby_count": "0"},
    ],
    "2020": [
        {"eid": "2-s2.0-85000000003", "doi": "10.1/c", "title": "C",
         "creator": "Roe B.", "coverDate": "2020-02-01",
         "publicationName": "Letters", "citedby_count": None},
        {"eid": None, "doi": "10.1/d", "title": "D", "creator": "Poe C.",
         "coverDate": "2020-03-01", "publicationName": None,
         "citedby_count": "7"},
    ],
}


def _plan():
    return sf.SearchPlan("graphene", years=[2019, 2020], field="TITLE-ABS-KEY",
                         partition="year")


def _harvest(monkeypatch):
    """A real fetch_plan() harvest, from a ScopusSearch double that answers each
    year cell with its own records and reports a total for it."""

    class _Search:
        def __init__(self, query, **kwargs):
            year = query.rsplit(" ", 1)[-1]
            self.results = [dict(row) for row in _ROWS[year]]

        def get_results_size(self):
            return len(self.results)

    scopus = types.ModuleType("pybliometrics.scopus")
    scopus.ScopusSearch = _Search
    pkg = types.ModuleType("pybliometrics")
    pkg.scopus = scopus
    monkeypatch.setitem(sys.modules, "pybliometrics", pkg)
    monkeypatch.setitem(sys.modules, "pybliometrics.scopus", scopus)
    return sf.fetch_plan(_plan())


def _markdown(records) -> str:
    return sf.scopus_search_report(records).format(style="markdown")


def test_a_harvest_survives_merge_groupby_apply_and_concat(monkeypatch):
    records = _harvest(monkeypatch)
    other = _harvest(monkeypatch)

    merged = records.merge(other[["scopus_id", "citations"]], on="scopus_id",
                           how="left", suffixes=("", "_later"))
    assert len(merged) == 4
    firsts = records.groupby("year")[["scopus_id", "doi"]].apply(lambda g: g.head(1))
    assert len(firsts) == 2
    both = pd.concat([records, other], ignore_index=True)
    assert len(both) == 8


def test_the_provenance_a_harvest_carries_is_json_safe(monkeypatch):
    records = _harvest(monkeypatch)
    json.dumps(records.attrs)

    assert records.attrs["plan"] == _plan().to_dict()
    assert sf.SearchPlan.from_dict(records.attrs["plan"]) == _plan()
    assert records.attrs["cell_totals"] == [
        {"cell": 1, "date": "2019", "n_records": 2, "reported_total": 2},
        {"cell": 2, "date": "2020", "n_records": 2, "reported_total": 2},
    ]
    stamp = records.attrs["retrieved_at"]
    assert isinstance(stamp, str)
    assert stamp.endswith("+00:00")
    parsed = datetime.fromisoformat(stamp)
    assert parsed.utcoffset() == timedelta(0)
    assert parsed.microsecond == 0
    assert isinstance(records.attrs["scopusflow_version"], str)


def test_a_plan_round_trips_through_its_dict():
    grid = [
        sf.SearchPlan("a b"),
        sf.SearchPlan("a b", years=range(2015, 2021), field="TITLE-ABS-KEY",
                      partition="year"),
        sf.SearchPlan('a "quoted" query', years=[2019], view="COMPLETE"),
        sf.SearchPlan("a b", years=[2020, 2016], page_size=37, partition="none"),
    ]
    for plan in grid:
        recorded = plan.to_dict()
        assert recorded["schema"] == 1
        assert sorted(recorded) == ["field", "page_size", "partition", "query",
                                    "schema", "view", "years"]
        assert sf.SearchPlan.from_dict(json.loads(json.dumps(recorded))) == plan
    assert sf.SearchPlan("x", years=[2016, 2015]).to_dict()["years"] == [2015, 2016]
    assert sf.SearchPlan("x").to_dict()["years"] is None

    with pytest.raises(ValueError, match="schema 2"):
        sf.SearchPlan.from_dict({**sf.SearchPlan("x").to_dict(), "schema": 2})
    with pytest.raises(ValueError, match="dict"):
        sf.SearchPlan.from_dict("x")


def test_parquet_keeps_the_provenance_and_the_record(monkeypatch, tmp_path):
    pytest.importorskip("pyarrow")
    records = _harvest(monkeypatch)
    path = tmp_path / "baseline.parquet"
    assert sf.write_records(records, path) is records

    restored = sf.read_records(path)
    assert restored.attrs == records.attrs
    assert list(restored.columns) == list(records.columns)
    assert list(restored["scopus_id"]) == list(records["scopus_id"])
    assert str(restored["scopus_id"].dtype) == "string"
    assert str(restored["citations"].dtype) == "Int64"
    assert _markdown(restored) == _markdown(records)


def test_parquet_stores_the_provenance_under_its_own_key(monkeypatch, tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    records = _harvest(monkeypatch)
    path = tmp_path / "baseline.parquet"
    sf.write_records(records, str(path))

    stored = json.loads(pq.read_schema(path).metadata[b"scopusflow"])
    assert stored == {"schema": 1, "attrs": records.attrs}


def test_attributes_set_by_hand_are_written_in_their_json_form(tmp_path):
    # The guides set a SearchPlan, a datetime and a DataFrame by hand, and the
    # record they render must survive the round trip unchanged.
    pytest.importorskip("pyarrow")
    plan = sf.SearchPlan("graphene supercapacitor", years=range(2015, 2025),
                         field="TITLE-ABS-KEY", partition="year")
    records = sf.example_records()
    records.attrs["plan"] = plan
    records.attrs["retrieved_at"] = datetime(2026, 7, 22, 9, 15, tzinfo=timezone.utc)
    records.attrs["scopusflow_version"] = "0.3.0"
    records.attrs["paging"] = "offset"
    per_year = records.groupby("year").size()
    records.attrs["cell_totals"] = pd.DataFrame({
        "cell": list(range(1, len(per_year) + 1)),
        "date": [str(y) for y in per_year.index],
        "n_records": list(per_year.values),
        "reported_total": list(per_year.values),
    })
    path = tmp_path / "hand.parquet"
    sf.write_records(records, path)

    restored = sf.read_records(path)
    assert restored.attrs["plan"] == plan.to_dict()
    assert restored.attrs["retrieved_at"] == "2026-07-22T09:15:00+00:00"
    assert restored.attrs["cell_totals"][2] == {
        "cell": 3, "date": "2017", "n_records": 10, "reported_total": 10}
    assert _markdown(restored) == _markdown(records)
    # The frame handed in keeps its own objects.
    assert records.attrs["plan"] is plan


def test_csv_keeps_identifiers_as_text_and_counts_as_integers(monkeypatch, tmp_path):
    records = _harvest(monkeypatch)
    path = tmp_path / "baseline.csv"
    sf.write_records(records, path)
    assert b"\r\n" not in path.read_bytes()

    restored = sf.read_records(path)
    assert restored.attrs == {}
    assert list(restored.columns) == list(records.columns)
    assert str(restored["scopus_id"].dtype) == "string"
    assert list(restored["scopus_id"].iloc[:3]) == ["85000000001", "85000000002",
                                                     "85000000003"]
    assert restored["scopus_id"].isna().iloc[3]
    assert str(restored["citations"].dtype) == "Int64"
    assert str(restored["year"].dtype) == "Int64"
    assert list(restored["citations"].fillna(-1)) == [3, 0, -1, 7]

    # The baseline read back still matches its own records in a fresh pull.
    fresh = _harvest(monkeypatch)
    merged = sf.scopus_combine(restored, fresh, dedupe=True)
    assert merged.attrs["combined"]["n_removed"] == 4
    assert len(merged) == 4


def test_dataframe_to_parquet_accepts_a_harvest(monkeypatch, tmp_path):
    pytest.importorskip("pyarrow")
    records = _harvest(monkeypatch)
    path = tmp_path / "plain.parquet"
    records.to_parquet(path)
    restored = pd.read_parquet(path)
    assert len(restored) == len(records)
    major, minor = (int(part) for part in pd.__version__.split(".")[:2])
    if (major, minor) >= (2, 1):
        assert restored.attrs == records.attrs


def test_the_extension_selects_the_format_and_nothing_else_is_accepted(tmp_path):
    records = sf.example_records()
    with pytest.raises(ValueError, match="'.parquet' or '.csv'"):
        sf.write_records(records, tmp_path / "records.xlsx")
    with pytest.raises(ValueError, match="'.parquet' or '.csv'"):
        sf.read_records(tmp_path / "records.rds")
    with pytest.raises(ValueError, match="record frame"):
        sf.write_records([1, 2], tmp_path / "records.csv")
    with pytest.raises(ValueError, match="single non-empty file path"):
        sf.write_records(records, "  ")
    with pytest.raises(FileNotFoundError):
        sf.read_records(tmp_path / "absent.csv")


def test_parquet_without_pyarrow_says_what_to_install(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)
    with pytest.raises(ImportError, match=r"scopusflow\[parquet\]"):
        sf.write_records(sf.example_records(), tmp_path / "records.parquet")
    with pytest.raises(ImportError, match=r"scopusflow\[parquet\]"):
        sf.read_records(tmp_path / "records.parquet")


def test_a_provenance_block_from_a_later_schema_is_refused(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    table = pa.Table.from_pandas(sf.example_records(), preserve_index=False)
    table = table.replace_schema_metadata({
        **table.schema.metadata,
        b"scopusflow": json.dumps({"schema": 2, "attrs": {}}).encode(),
    })
    path = tmp_path / "later.parquet"
    pq.write_table(table, path)
    with pytest.raises(ValueError, match="schema 2"):
        sf.read_records(path)


def test_a_parquet_written_without_scopusflow_reads_with_no_provenance(tmp_path):
    pytest.importorskip("pyarrow")
    path = tmp_path / "bare.parquet"
    sf.example_records().to_parquet(path)
    restored = sf.read_records(path)
    assert restored.attrs == {}
    assert len(restored) == 138
    assert str(restored["doi"].dtype) == "string"
