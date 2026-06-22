# scopusflow (Python)

A reproducible **workflow layer over [pybliometrics](https://pybliometrics.readthedocs.io)**
for Scopus searches. It is the Python twin of the R package
[scopusflow](https://pablobernabeu.github.io/scopusflow/).

> Status: early scaffold (`0.1.0.dev0`). The pure-logic parts (plans, query
> building, schema, DOI diffing) work today; the `fetch_plan` integration is a
> thin driver over pybliometrics and should be confirmed against your installed
> version before relying on it.

## Why this exists

pybliometrics is the mature, well-maintained way to *reach* the Scopus API in
Python — it wraps about ten endpoints and handles HTTP, cursor pagination,
weekly-quota rotation and per-query caching. It does **not**, however, give you a
workflow: a declarative search plan, a single stable record schema across query
types, a resumable project-level harvest with checkpoints, DOI change-tracking
between runs, annual publication trends, batch abstract retrieval or ready-made
plots. Researchers hand-roll those around pybliometrics today.

scopusflow fills exactly that gap, and deliberately depends on pybliometrics
rather than re-implementing the plumbing it already does well.

| | pybliometrics | scopusflow (this) |
|---|---|---|
| Reach the API (search, retrieval, quota, cursor, cache) | ✅ | delegates to pybliometrics |
| Declarative, reproducible search plan | — | ✅ |
| One stable tidy record schema across query types | — | ✅ |
| Resumable, checkpointed harvest of a plan | — | ✅ |
| DOI extraction + change-tracking between runs | — | ✅ |
| Annual publication trends without downloading records | — | ✅ |
| Topic-trend comparison with stability bands | — | ✅ |
| Batch abstract retrieval, resilient per id | — | ✅ |
| Ready-made trend and top-source/author plots | — | ✅ |
| Export to reference managers (BibTeX, RIS) | — | ✅ |

The other Python options are not live competitors: `elsapy` was archived
(read-only, Jan 2025) and `pyscopus` has had no release since 2018.

## Install

```bash
pip install scopusflow            # once published
pip install -e ".[dev,plot]"      # from a clone, for development
```

You need a Scopus API key configured for pybliometrics (its standard
`~/.config/pybliometrics.cfg`).

## Quick start

```python
import scopusflow as sf

# Build a field-tagged query and a reproducible, year-partitioned plan.
q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2010, 2023), partition="year")

# Harvest it, caching each year so an interrupted run resumes.
records = sf.fetch_plan(plan, cache_dir="harvest", resume=True)

# A stable schema feeds the rest.
sf.top(records, by="source")
dois = sf.extract_dois(records)

# Re-run later and see exactly what changed.
later = sf.fetch_plan(plan, cache_dir="harvest2")
sf.diff_dois(old=records, new=later)

# See the publication trend over time — either tallied from the harvest you
# already have, or fetched directly as cheap per-year result-size lookups that
# never download the records themselves.
trend = sf.year_counts(records)
trend = sf.scopus_trend(q, years=range(2010, 2023))

# Compare how sub-topics grow within the reference literature over time.
cmp = sf.compare_topics(q, ["lithium-ion", "sodium-ion"], years=range(2015, 2023))
sf.plot_comparison(cmp)

# Pull the abstracts you care about, resilient to the odd id that fails.
abstracts = sf.scopus_abstract(dois[:10], by="doi")

# Turn the summaries into figures (needs the optional `plot` extra).
sf.plot_trend(trend)
sf.plot_top(sf.top(records, by="source"))

# Export for a reference manager (Zotero, EndNote) or a LaTeX bibliography.
open("scopus-records.bib", "w", encoding="utf-8").write(sf.to_bibtex(records))
```

The pure-logic helpers (`scopus_query`, `SearchPlan`, `to_records`, `top`,
`extract_dois`, `diff_dois`, `year_counts`) need no API key and are covered by
the offline tests. The live helpers (`fetch_plan`, `scopus_trend`,
`scopus_abstract`) call pybliometrics, and the plots (`plot_trend`, `plot_top`)
need the optional `plot` extra.

## Code-free app

A local [NiceGUI](https://nicegui.io) app drives the whole workflow without
writing code, and mirrors every choice back as a runnable Python script, so it is
an on-ramp to the package rather than a replacement. It runs on your own machine,
so the API key never leaves it. A built-in demo mode lets you try the flow with
synthetic data and no key.

```bash
pip install "scopusflow[app]"
scopusflow-gui
```

The retrieval runs in the background with a live progress terminal; results show
as a paginated table and plots, with one-click export. It is the Python twin of
the R package's `scopusflow::run_app()`.

## Licence

MIT. Scopus is a trademark of Elsevier; this is an independent client and is not
affiliated with or endorsed by Elsevier.
