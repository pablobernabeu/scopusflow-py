# scopusflow (Python)

<!-- badges: start -->
[![tests](https://github.com/pablobernabeu/scopusflow-py/actions/workflows/tests.yaml/badge.svg)](https://github.com/pablobernabeu/scopusflow-py/actions/workflows/tests.yaml)
[![docs](https://github.com/pablobernabeu/scopusflow-py/actions/workflows/docs.yml/badge.svg)](https://pablobernabeu.github.io/scopusflow-py/)
[![PyPI](https://img.shields.io/pypi/v/scopusflow)](https://pypi.org/project/scopusflow/)
[![Python versions](https://img.shields.io/pypi/pyversions/scopusflow)](https://pypi.org/project/scopusflow/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/license/MIT)
[![DOI 10.5281/zenodo.21252666](https://zenodo.org/badge/DOI/10.5281/zenodo.21252666.svg)](https://doi.org/10.5281/zenodo.21252666)
<!-- badges: end -->

Documentation: <https://pablobernabeu.github.io/scopusflow-py/>

scopusflow is a reproducible workflow layer over [pybliometrics](https://pybliometrics.readthedocs.io) for Scopus searches. It is the Python twin of [the R package](https://pablobernabeu.github.io/scopusflow/) of the same name and follows the same design, so a search written in one language reads much the same in the other.

This is an early release, covered by an offline test suite. Its retrieval code is a thin layer over pybliometrics, so a short trial run against your installed version is worth doing before a large live harvest.

## Why this exists

pybliometrics is the mature way to reach the Scopus API from Python. It wraps about ten endpoints and handles the HTTP requests, cursor pagination, weekly-quota rotation and per-query caching. It does not provide a workflow built on them. There is no declarative search plan, no single record schema that stays the same across query types, no resumable harvest with checkpoints, no DOI change-tracking between runs, and nothing ready-made for trends, topic comparisons, abstracts or plots. Researchers tend to write these parts themselves around pybliometrics, and scopusflow provides them. It depends on pybliometrics and re-implements nothing that pybliometrics already does well.

| | pybliometrics | scopusflow |
|---|---|---|
| Reach the API (search, retrieval, quota, cursor, cache) | yes | delegates to pybliometrics |
| Declarative, reproducible search plan | no | yes |
| One stable record schema across query types | no | yes |
| Resumable, checkpointed harvest of a plan | no | yes |
| DOI extraction and change-tracking between runs | no | yes |
| Annual publication trends without downloading records | no | yes |
| Topic-trend comparison with stability bands | no | yes |
| Batch abstract retrieval, resilient per id | no | yes |
| Trend and top-source/author plots | no | yes |
| Export to reference managers (BibTeX, RIS) | no | yes |
| PRISMA-S search record for a methods section | no | yes |
| Minimal, uniform keyword/reference corpus export | no | yes |

The other Python options are not viable alternatives. elsapy was archived as read-only in January 2025, and pyscopus had its last release in January 2019.

## Installation

The released version is on PyPI.

```bash
pip install scopusflow
```

The development version, which may be ahead of the release on PyPI, installs from GitHub.

```bash
pip install git+https://github.com/pablobernabeu/scopusflow-py.git
```

The optional extras add the plots, the app and parquet support. Install `scopusflow[plot]` for the matplotlib plots and `scopusflow[app]` for the code-free app. With `scopusflow[parquet]` installed, `write_records()` and `read_records()` save a harvest with its provenance as `.parquet` and read it back. To work on the package itself, install from a clone with `pip install -e ".[dev,plot]"`.

You need a Scopus API key, which pybliometrics keeps in its configuration file, `~/.config/pybliometrics.cfg`. pybliometrics 4 reads that file only when `pybliometrics.init()` is called, once in every session, and the first call creates the file and asks for your key.

## A first search

The example below builds a query, plans a harvest partitioned by year, retrieves it with caching and then draws on the stable record schema for everything that follows. It starts by initialising pybliometrics, without which the first search stops with `ScopusFlowConfigError`.

```python
import pybliometrics

import scopusflow as sf

pybliometrics.init()   # once per session, before the first search

q = sf.scopus_query("graphene", "supercapacitor", field="TITLE-ABS-KEY")
plan = sf.SearchPlan(q, years=range(2015, 2025), partition="year")

records = sf.fetch_plan(plan, cache_dir="harvest", resume=True)

sf.top(records, by="source")
dois = sf.extract_dois(records)
```

Re-running the same plan later and comparing the two retrievals shows which records have appeared or disappeared in the meantime.

```python
later = sf.fetch_plan(plan, cache_dir="harvest2")
sf.diff_dois(old=records, new=later)
```

The second run asks the API again and spends quota. The checkpoints in `cache_dir` are there to let an interrupted harvest resume. pybliometrics keeps a response cache of its own, which would return the earlier results from disk when the search is repeated. scopusflow therefore bypasses that cache unless you pass `refresh=False`. The [guide to plans and quota](https://pablobernabeu.github.io/scopusflow-py/guides/plans-and-quota/#re-running-and-tracking-change) explains both caches.

The publication trend can be tallied from a harvest you already hold, or fetched directly as cheap per-year result-size lookups that never download the records themselves.

```python
trend = sf.year_counts(records)
trend = sf.scopus_trend(q, years=range(2015, 2025))
```

A topic comparison shows how sub-topics grow within the reference literature over time. The abstract and export helpers retrieve abstracts for reading and format the records for a reference manager.

```python
cmp = sf.compare_topics(q, ["lithium-ion", "sodium-ion"], years=range(2015, 2023))
sf.plot_comparison(cmp)

abstracts = sf.scopus_abstract(dois[:10], by="doi")

with open("scopus-records.bib", "w", encoding="utf-8") as fh:
    fh.write(sf.to_bibtex(records))
```

Writing the search up usually follows a harvest, and `scopus_search_report` does it to the PRISMA-S standard from what the plan and the harvest already record. The report can be printed as a readable record, formatted as a methods paragraph or written to a Markdown file. It states only what the objects hold, so a retrieval time, matching total or de-duplication step that the harvest never recorded is reported as unrecorded. The PRISMA-S items that the package cannot determine are listed as yours to supply.

```python
report = sf.scopus_search_report(records)
print(report.format(style="paragraph"))
sf.scopus_search_report(records, file="search-record.md")
```

The pure-logic helpers, from query building to DOI tracking, need no API key and are exercised by the offline tests. Everything that contacts the API needs a key, and the plots need the optional `plot` extra. To try the analysis half before configuring anything, use `sf.example_records()`, which returns a bundled set of 138 real articles in the same schema. It is not a Scopus harvest, since retrieved records may not be redistributed. The [documentation](https://pablobernabeu.github.io/scopusflow-py/guides/getting-started/#the-bundled-harvest) explains where it comes from.

## A code-free app

A local [NiceGUI](https://nicegui.io) app lets you run the whole workflow without writing code. Because it shows every choice as a runnable Python script, the app is also a way into the package. It runs on your own machine, so your API key never leaves it. A demo mode lets you try the workflow with no key, replaying the bundled set of real published articles in place of a harvest.

```bash
pip install "scopusflow[app]"
scopusflow-gui
```

The retrieval runs in the background with a live progress terminal. Results appear as a paginated table and a pair of plots with one-click export, and a 'Compare topics' card draws the same comparison figure the library produces.

## Citation

If scopusflow contributes to published work, please cite it. GitHub builds a ready-made citation from [`CITATION.cff`](https://github.com/pablobernabeu/scopusflow-py/blob/main/CITATION.cff) through the 'Cite this repository' button.

> Bernabeu, P. (2026). scopusflow: A reproducible workflow layer over pybliometrics for Scopus searches. Python package version 0.3.0. <https://doi.org/10.5281/zenodo.21252666>

The [About page](https://pablobernabeu.github.io/scopusflow-py/about/) carries the same citation with a BibTeX entry.

## Developer

scopusflow is written by [Pablo Bernabeu](https://pablobernabeu.github.io/), a researcher in the Department of Education at the University of Oxford, with hands-on experience of behavioural experiments, EEG, corpus analysis, computational modelling and statistics. He develops open, reproducible research software in R and Python, and is a Fellow of the Software Sustainability Institute. His [ORCID record](https://orcid.org/0000-0003-1083-2460) lists his other work.

## Licence

MIT. Scopus is a trademark of Elsevier. scopusflow is an independent client and is not affiliated with or endorsed by Elsevier.

## Contributing

Issues and pull requests are welcome. The [contributing guide](https://github.com/pablobernabeu/scopusflow-py/blob/main/.github/CONTRIBUTING.md) covers the development setup and the conventions the package follows, and everyone taking part is asked to honour the [Code of Conduct](https://github.com/pablobernabeu/scopusflow-py/blob/main/.github/CODE_OF_CONDUCT.md).
