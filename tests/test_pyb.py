"""pybliometrics' own response cache, and what scopusflow makes of it.

pybliometrics files every search under ``{dir}/{view}/md5(query)`` and, unless
``refresh`` is True, answers a repeat of the query from that file without a
request, reporting the cached rows as the result size. The first tests drive
the real pybliometrics against a configuration kept under ``tmp_path`` and a
stubbed transport, so no request leaves the machine and the user's own
configuration and cache are never read or written. One of them runs a
COMPLETE-view entry through the real parser, to hold the authors column to the
R twin's. The rest test the helpers that recognise a cached answer, on stand-in
objects.
"""

import json
import os
import sys
import time
import warnings
from configparser import ConfigParser
from datetime import datetime, timezone

import pytest

#: A cache file's time in the tests. It is fixed, and far from any change of
#: the clocks, so its local rendering reads back as the same instant in every
#: time zone.
WRITTEN = datetime(2026, 7, 1, 9, 30, 15, tzinfo=timezone.utc)


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {"X-RateLimit-Remaining": "19999", "X-RateLimit-Reset": "1790000000"}
        self.text = json.dumps(payload)
        self.status_code = 200

    def json(self):
        return self._payload


class _CannedScopus:
    """Stands in for pybliometrics' transport, one canned page per request."""

    def __init__(self):
        self.calls = 0
        self.total = 0
        self.entries = []

    def serve(self, total, n_entries):
        self.total = total
        # 10.5555 is the DOI prefix reserved for tests.
        self.entries = [
            {"eid": f"2-s2.0-8500000{i:04d}", "prism:doi": f"10.5555/cache.{i}",
             "dc:title": f"Record {i}", "prism:coverDate": "2020-05-01",
             "prism:publicationName": "Journal", "citedby-count": "1", "openaccess": "0"}
            for i in range(1, n_entries + 1)
        ]

    def __call__(self, url, api, params=None, **kwds):
        self.calls += 1
        return _Response({"search-results": {
            "opensearch:totalResults": str(self.total),
            "entry": [dict(e) for e in self.entries],
            "cursor": {"@next": "next"},
        }})


@pytest.fixture
def scopus_api(tmp_path, monkeypatch):
    """The real pybliometrics, configured under ``tmp_path``, transport stubbed."""
    # Other tests put stand-in modules under these names. Each restores what it
    # replaced, but none may stand in for the real package here.
    for name in [n for n in list(sys.modules)
                 if n == "pybliometrics" or n.startswith("pybliometrics.")]:
        if getattr(sys.modules[name], "__file__", None) is None:
            monkeypatch.delitem(sys.modules, name)
    pytest.importorskip("pybliometrics.scopus")
    import pybliometrics.superclasses.base as base
    from pybliometrics.utils import startup
    from pybliometrics.utils.constants import DEFAULT_PATHS

    config = ConfigParser()
    config.optionxform = str
    config.add_section("Directories")
    for api in DEFAULT_PATHS:
        config.set("Directories", api, str(tmp_path / "pybliometrics" / api))
    config.add_section("Authentication")
    config.set("Authentication", "APIKey", "not-a-real-key")
    config.add_section("Requests")
    # Set in place of pybliometrics.init(), which would read the user's own
    # configuration and leave these globals set for every later test.
    monkeypatch.setattr(startup, "CONFIG", config)
    monkeypatch.setattr(startup, "CUSTOM_KEYS", ["not-a-real-key"])
    monkeypatch.setattr(startup, "CUSTOM_INSTTOKENS", None)
    startup.create_cache_folders(config)
    api = _CannedScopus()
    monkeypatch.setattr(base, "get_content", api)
    return api


def _search_cache(tmp_path):
    return tmp_path / "pybliometrics" / "ScopusSearch" / "STANDARD"


def _plan():
    import scopusflow as sf

    return sf.SearchPlan("graphene supercapacitor", years=[2020],
                         field="TITLE-ABS-KEY", partition="year")


def test_a_rerun_into_a_fresh_cache_dir_asks_the_api_again(scopus_api, tmp_path):
    # The change-tracking workflow: harvest, wait, harvest again into a new
    # directory, diff. pybliometrics' cache used to answer the second run
    # with the first pull, dated now, so the diff compared a harvest with
    # itself.
    import scopusflow as sf

    scopus_api.serve(total=2, n_entries=2)
    first = sf.fetch_plan(_plan(), cache_dir=str(tmp_path / "harvest-1"))
    assert scopus_api.calls == 1

    scopus_api.serve(total=3, n_entries=3)   # the literature has grown
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        later = sf.fetch_plan(_plan(), cache_dir=str(tmp_path / "harvest-2"))
    assert scopus_api.calls == 2
    assert len(later) == 3
    assert [c["reported_total"] for c in later.attrs["cell_totals"]] == [3]
    assert later.attrs["total_results"] == 3
    status = sf.diff_dois(old=first, new=later)["status"]
    assert sorted(status) == ["added", "unchanged", "unchanged"]


def test_a_rerun_after_a_short_harvest_still_warns_of_the_shortfall(scopus_api, tmp_path):
    # Served from the cache, a truncated cell reported its own row count as
    # the total, so the shortfall check compared the rows with themselves.
    import scopusflow as sf

    scopus_api.serve(total=5, n_entries=2)
    with pytest.warns(UserWarning, match="harvest may be incomplete"):
        sf.fetch_plan(_plan(), cache_dir=str(tmp_path / "harvest-1"))
    with pytest.warns(UserWarning, match="harvest may be incomplete"):
        later = sf.fetch_plan(_plan(), cache_dir=str(tmp_path / "harvest-2"))
    assert scopus_api.calls == 2
    assert later.attrs["total_results"] == 5


def test_counts_after_a_harvest_come_from_the_api(scopus_api, tmp_path):
    # A count is sent with the very query string a year cell was harvested
    # under, so the cache used to answer it with the cell's row count. A
    # comparison then mixed that cached reference with fresh counts: 3 of 2,
    # or 150%.
    import scopusflow as sf

    q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
    scopus_api.serve(total=4, n_entries=2)
    with pytest.warns(UserWarning, match="harvest may be incomplete"):
        sf.fetch_plan(sf.SearchPlan(q, years=[2020], partition="year"),
                      cache_dir=str(tmp_path / "harvest"))

    scopus_api.serve(total=3, n_entries=1)   # every count now reports 3
    calls = scopus_api.calls
    cmp = sf.compare_topics(q, ["electrode"], years=[2020])
    row = cmp[cmp["query_type"] == "comparison"].iloc[0]
    assert row["comparison_percentage"] == 100.0
    assert row["reference_n"] == 3
    assert scopus_api.calls == calls + 2

    assert sf.scopus_count(q, years=[2020]) == 3
    assert list(sf.scopus_trend(q, years=[2020])["n"]) == [3]
    assert list(sf.scopus_intersections({"graphene": q}, years=[2020])["n"]) == [3]
    assert scopus_api.calls == calls + 5


def test_a_harvest_served_from_the_cache_on_request_says_so(scopus_api, tmp_path):
    # refresh=False opts in to pybliometrics' cache. The cell it serves is
    # dated by the cache file and claims no total, and a warning says so.
    import scopusflow as sf

    scopus_api.serve(total=2, n_entries=2)
    sf.fetch_plan(_plan(), cache_dir=str(tmp_path / "harvest-1"))
    (cache_file,) = _search_cache(tmp_path).iterdir()
    os.utime(cache_file, (WRITTEN.timestamp(), WRITTEN.timestamp()))

    scopus_api.serve(total=3, n_entries=3)
    with pytest.warns(UserWarning, match="pybliometrics' own cache") as caught:
        later = sf.fetch_plan(_plan(), cache_dir=str(tmp_path / "harvest-2"),
                              refresh=False)
    assert scopus_api.calls == 1             # answered from the cache, as asked
    assert len(later) == 2
    assert "2026-07-01 09:30:15 UTC" in str(caught[0].message)
    assert [c["reported_total"] for c in later.attrs["cell_totals"]] == [None]
    assert later.attrs["total_results"] is None
    assert later.attrs["retrieved_at"] == WRITTEN.isoformat(timespec="seconds")


def test_a_cache_file_written_moments_before_is_still_recognised(scopus_api, tmp_path):
    # The cache file's time has whole seconds only, so a file written in the
    # second the search began looks as new as a fresh answer. pybliometrics
    # keeps no response headers for an answer it read from disk, which tells
    # the two apart.
    import scopusflow as sf

    q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
    scopus_api.serve(total=2, n_entries=2)
    sf.fetch_plan(sf.SearchPlan(q, years=[2020], partition="year"))

    with pytest.warns(UserWarning, match="pybliometrics' own cache"):
        n = sf.scopus_count(q, years=[2020], refresh=False)
    assert n == 2
    assert scopus_api.calls == 1

    with pytest.warns(UserWarning, match="pybliometrics' own cache"):
        again = sf.fetch_plan(sf.SearchPlan(q, years=[2020], partition="year"),
                              refresh=False)
    assert scopus_api.calls == 1
    assert again.attrs["total_results"] is None


def test_a_complete_harvest_lists_the_authors_the_r_twin_lists(scopus_api):
    # The shared fixture's entry goes through the real parser, so the
    # author_names string the fixture records, and the authors column built
    # from it, are both held to what pybliometrics does. The R suite parses
    # the same entry, byte for byte, and expects the same string.
    from pathlib import Path

    from pybliometrics.scopus import ScopusSearch

    import scopusflow as sf

    path = Path(__file__).resolve().parent / "fixtures" / "complete-authors.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    plan = sf.SearchPlan("genome editing", years=[2013], partition="year",
                         view="COMPLETE")

    scopus_api.total, scopus_api.entries = 1, [fixture["entry"]]
    parsed = ScopusSearch("genome editing", view="COMPLETE", refresh=True).results
    assert parsed[0].author_names == fixture["author_names"]
    out = sf.fetch_plan(plan)
    assert out.loc[0, "authors"] == fixture["expected_authors"]
    assert out.attrs["view"] == "COMPLETE"

    blank = json.loads(json.dumps(fixture["entry"]))
    blank["author"] = fixture["blank_given_names"]["author"]
    scopus_api.entries = [blank]
    parsed = ScopusSearch("genome editing", view="COMPLETE", refresh=True).results
    assert parsed[0].author_names == fixture["blank_given_names"]["author_names"]
    assert sf.fetch_plan(plan).loc[0, "authors"] == (
        fixture["blank_given_names"]["expected_authors"])

    # Where an author object lacks a given-name or a surname key, an edge both
    # twins document, pybliometrics builds no author_names at all, so the first
    # author stands here while the R twin lists every author.
    for key in ("given-name", "surname"):
        keyless = json.loads(json.dumps(fixture["entry"]))
        del keyless["author"][3][key]
        scopus_api.entries = [keyless]
        assert sf.fetch_plan(plan).loc[0, "authors"] == "Cong L."

    # A null surname is written after a bare comma, where the R twin names
    # that author by the indexed form, "Doudna J.A.".
    nameless = json.loads(json.dumps(fixture["entry"]))
    nameless["author"][3]["surname"] = None
    scopus_api.entries = [nameless]
    assert sf.fetch_plan(plan).loc[0, "authors"] == (
        "Cong, Le; Zhang, Feng; , Jennifer A.")


# A session that has not initialised pybliometrics.

@pytest.fixture
def uninitialised(tmp_path, monkeypatch):
    """The real pybliometrics as a fresh session finds it, before init()."""
    for name in [n for n in list(sys.modules)
                 if n == "pybliometrics" or n.startswith("pybliometrics.")]:
        if getattr(sys.modules[name], "__file__", None) is None:
            monkeypatch.delitem(sys.modules, name)
    pytest.importorskip("pybliometrics.scopus")
    from pybliometrics.utils import startup

    config_file = tmp_path / ".config" / "pybliometrics.cfg"
    monkeypatch.setattr(startup, "CONFIG", None)
    monkeypatch.setattr(startup, "CONFIG_FILE", config_file)
    return config_file


def _abstract(**kwargs):
    import scopusflow as sf

    return sf.scopus_abstract(["85000000001"], **kwargs)


@pytest.mark.parametrize("call", [
    lambda sf: sf.fetch_plan(_plan()),
    lambda sf: sf.scopus_count("graphene", years=[2020]),
    lambda sf: sf.scopus_trend("graphene", years=[2020]),
    lambda sf: sf.compare_topics("graphene", ["electrode"], years=[2020]),
    lambda sf: _abstract(),
], ids=["fetch_plan", "scopus_count", "scopus_trend", "compare_topics", "scopus_abstract"])
def test_a_search_before_init_says_what_to_run(uninitialised, call):
    # pybliometrics 4 needs init() in every session. Without it, the first
    # search stopped on "No configuration file found", even with a valid
    # configuration file in place, and scopus_abstract() logged that failure
    # against each identifier in turn.
    import scopusflow as sf

    with pytest.raises(sf.ScopusFlowConfigError) as caught:
        call(sf)
    message = str(caught.value)
    assert "pybliometrics.init()" in message
    assert str(uninitialised) in message
    assert isinstance(caught.value, RuntimeError)


def test_require_init_passes_once_pybliometrics_is_initialised(uninitialised, monkeypatch):
    from configparser import ConfigParser

    from pybliometrics.utils import startup

    from scopusflow._pyb import require_init

    monkeypatch.setattr(startup, "CONFIG", ConfigParser())
    assert require_init() is None


def test_require_init_leaves_a_stand_in_module_alone(monkeypatch):
    # The offline suites put a bare pybliometrics with a scopus module alone
    # under sys.modules. The real startup module may be loaded alongside it,
    # still uninitialised, and must not be read in its place.
    import types

    from scopusflow._pyb import require_init

    pkg = types.ModuleType("pybliometrics")
    pkg.scopus = types.ModuleType("pybliometrics.scopus")
    monkeypatch.setitem(sys.modules, "pybliometrics", pkg)
    monkeypatch.setitem(sys.modules, "pybliometrics.scopus", pkg.scopus)
    assert require_init() is None


def test_a_harvest_resumed_from_checkpoints_needs_no_init(scopus_api, tmp_path, monkeypatch):
    # A resumed cell sends no request, so a finished harvest read back in a
    # fresh session has nothing to initialise pybliometrics for. Checking on
    # entry would refuse it.
    from pybliometrics.utils import startup

    import scopusflow as sf

    scopus_api.serve(total=2, n_entries=2)
    harvest = str(tmp_path / "harvest")
    first = sf.fetch_plan(_plan(), cache_dir=harvest, format="csv")
    calls = scopus_api.calls

    monkeypatch.setattr(startup, "CONFIG", None)
    again = sf.fetch_plan(_plan(), cache_dir=harvest, format="csv", resume=True)
    assert scopus_api.calls == calls
    assert list(again["doi"]) == list(first["doi"]) == ["10.5555/cache.1", "10.5555/cache.2"]

    # A cell that does need a request is still stopped before it is sent.
    with pytest.raises(sf.ScopusFlowConfigError):
        sf.fetch_plan(_plan(), cache_dir=harvest, format="csv", resume=False)
    assert scopus_api.calls == calls


def test_abstracts_resumed_from_checkpoints_need_no_init(uninitialised, tmp_path):
    import pandas as pd

    import scopusflow as sf
    from scopusflow.abstract import ABSTRACT_COLUMNS, _write_abstract_checkpoint

    cache = tmp_path / "abstracts"
    cache.mkdir()
    row = {col: pd.NA for col in ABSTRACT_COLUMNS}
    row.update(doi="10.5555/resumed.1", title="Resumed")
    _write_abstract_checkpoint(row, cache, "META_ABS", (), "10.5555/resumed.1")

    out = sf.scopus_abstract(["10.5555/resumed.1"], cache_dir=str(cache))
    assert list(out["title"]) == ["Resumed"]

    # A second identifier with no checkpoint needs a request, and is stopped
    # before it with the same error, never recorded as an NA row.
    with pytest.raises(sf.ScopusFlowConfigError):
        sf.scopus_abstract(["10.5555/resumed.1", "10.5555/missing.2"],
                           cache_dir=str(cache))


# The helpers behind those warnings, on stand-in objects.

def _local(instant):
    """``instant`` as pybliometrics' ``get_cache_file_mdate()`` renders it."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(instant.timestamp()))


class _Answer:
    """A stand-in exposing the two public getters pybliometrics' searches carry."""

    def __init__(self, file_time, remaining="19999"):
        self._file_time = file_time
        self._remaining = remaining

    def get_cache_file_mdate(self):
        if isinstance(self._file_time, Exception):
            raise self._file_time
        return self._file_time

    def get_key_remaining_quota(self):
        if isinstance(self._remaining, Exception):
            raise self._remaining
        return self._remaining


def test_only_refresh_true_keeps_pybliometrics_from_its_cache():
    from scopusflow._pyb import may_use_cache

    assert may_use_cache(True) is False
    # False always reads an existing file, and a number reads one younger than
    # that many days. pybliometrics takes 1 as a number of days, not as True.
    assert may_use_cache(False) is True
    assert may_use_cache(7) is True
    assert may_use_cache(1) is True


def test_a_fresh_answer_is_not_a_cache_hit():
    from scopusflow._pyb import cache_hit_time

    t0 = WRITTEN.timestamp() - 0.3          # the search began just before the response
    assert cache_hit_time(_Answer(_local(WRITTEN)), t0) is None
    # A response without the rate-limit header makes the quota getter raise
    # KeyError, which still shows there was a response.
    no_header = _Answer(_local(WRITTEN), KeyError("X-RateLimit-Remaining"))
    assert cache_hit_time(no_header, t0) is None


def test_an_older_cache_file_marks_a_hit_and_dates_it():
    from scopusflow._pyb import cache_hit_time

    t0 = WRITTEN.timestamp() + 3600
    assert cache_hit_time(_Answer(_local(WRITTEN), None), t0) == WRITTEN
    # The file's time is enough on its own, whatever the quota getter says.
    assert cache_hit_time(_Answer(_local(WRITTEN)), t0) == WRITTEN


def test_missing_response_headers_mark_a_hit_from_the_same_second():
    from scopusflow._pyb import cache_hit_time

    t0 = WRITTEN.timestamp() + 0.4          # the second the file was written in
    assert cache_hit_time(_Answer(_local(WRITTEN), None), t0) == WRITTEN
    assert cache_hit_time(_Answer(_local(WRITTEN)), t0) is None


def test_a_stand_in_without_either_getter_counts_as_fetched():
    from scopusflow._pyb import cache_hit_time

    assert cache_hit_time(object(), time.time()) is None


@pytest.mark.parametrize("file_time", ["yesterday", None, OSError("no cache file")])
def test_an_unreadable_cache_time_leaves_the_answer_undated(file_time):
    # An unexpected rendering must never pass for a fresh answer.
    from scopusflow._pyb import UNDATED, cache_hit_time

    assert cache_hit_time(_Answer(file_time), WRITTEN.timestamp()) is UNDATED
    assert cache_hit_time(_Answer(file_time, None), WRITTEN.timestamp()) is UNDATED


def test_missing_headers_without_a_file_time_mark_an_undated_hit():
    from scopusflow._pyb import UNDATED, cache_hit_time

    class _QuotaOnly:
        def __init__(self, remaining):
            self._remaining = remaining

        def get_key_remaining_quota(self):
            return self._remaining

    assert cache_hit_time(_QuotaOnly(None), time.time()) is UNDATED
    assert cache_hit_time(_QuotaOnly("19999"), time.time()) is None


@pytest.fixture
def uk_local_time():
    """The process's local time zone set to the United Kingdom's where the
    platform allows it, so the test below runs on a CI runner kept on UTC.
    ``time.tzset`` exists on POSIX systems only, and elsewhere the machine's
    own zone stands."""
    if not hasattr(time, "tzset"):
        yield
        return
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/London"
    time.tzset()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def test_the_hour_repeated_when_the_clocks_go_back_is_read_both_ways(uk_local_time):
    # pybliometrics renders the file's time in local time, so in the hour the
    # clocks repeat one rendering stands for two instants. A fresh answer must
    # not be taken for an hour-old file, and a hit is dated by the earlier
    # instant, so a record never claims a fresher search than it ran.
    from scopusflow._pyb import cache_hit_time

    rendered = "2026-10-25 01:30:00"
    local = datetime(2026, 10, 25, 1, 30)
    first = local.replace(fold=0).astimezone(timezone.utc)
    second = local.replace(fold=1).astimezone(timezone.utc)
    if first == second:
        pytest.skip("the local time zone does not repeat 01:30 on 25 October 2026")
    earlier, later = sorted((first, second))
    assert cache_hit_time(_Answer(rendered), later.timestamp() - 0.5) is None
    assert cache_hit_time(_Answer(rendered, None), later.timestamp() + 7200) == earlier
