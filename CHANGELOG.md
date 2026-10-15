# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

This section is prepared as 0.4.0, which has not been released, so PyPI still
carries 0.3.0.

### Added

- `scopus_search_report()` writes the search up. It assembles the reproducible
  search-strategy record a systematic review has to report, from a harvest or from a
  plan not yet run: the database and platform, the field-wrapped query of every cell,
  the year limits, view, page size and paging mode, the date searched, the records
  retrieved against the number the API reported as matching, per-cell completeness,
  duplicates removed, the software versions, a runnable snippet that rebuilds the plan,
  and an explicit map of which PRISMA-S items the package can supply and which only the
  author can. `print(report)` shows the readable record,
  `report.format(style="paragraph")` gives a methods paragraph fit to paste into a
  manuscript, and `file=` writes the whole record as Markdown. The standard is PRISMA-S
  (Rethlefsen et al., 2021, Systematic Reviews, 10, 39) with the identification counts
  of the PRISMA 2020 flow diagram.

  Because the output is written for a published methods section, the record states only
  what the objects hold. An absent retrieval time is never replaced by the current one,
  a completeness figure is never given for a harvest whose reported total is unknown,
  duplicates are counted only where a merge recorded removing them, and every
  unverifiable field says it is unrecorded, in words. The rendering is byte-identical to
  the R twin's, pinned in both repositories by `tests/golden-search-record.txt`.

- `scopus_combine()`, the counterpart of the R twin's function of the same name.
  It binds record frames, renumbers `entry_number`, optionally drops the records they
  share (by Scopus identifier, failing that by DOI, case-insensitively), and records the
  merge in `attrs["combined"]`: how many went in, how many were kept, how many were
  removed and whether de-duplication ran. The guides showed this by hand with
  `pandas.concat` and a duplicate mask; that count exists only at the moment of the
  merge, and PRISMA-S asks for it.

- `SearchPlan` carries `page_size`, defaulting to the largest page the view allows
  (200 for `STANDARD`, 25 for `COMPLETE`), which is what pybliometrics already requests
  for each view. It is sent with the search, so the page size a search record states is
  the one the harvest actually used.

- CI now covers what users actually install, over and above the checkout. The
  matrix gains Python 3.14. A new job installs the built wheel into a bare
  environment outside the repository and imports it there, so packaged data and
  distribution metadata are
  exercised in their own right, where the source tree an editable install sits next to
  would otherwise mask them. A second new job installs the declared minimum dependency
  versions, which were an untested promise to anyone resolving against an older stack;
  a failure there means the floors need raising to what actually works. A weekly
  schedule runs the suite when nobody has pushed, so upstream drift shows up as a dated
  red badge before it can surprise anyone.

- `scopus_trend()` accepts a `field` argument, wrapping the query in a Scopus
  field tag once before the per-year counts, as `scopus_count()` and the R
  twin's `scopus_trend()` already do.

- The guide to designing queries describes the offline query checks and gives a recipe
  for testing a strategy's relative recall against records known to be relevant, with
  two searches per chain of DOIs (Sampson et al., 2006; Bramer et al., 2018). The
  recipe contacts the API and is not run in the guide.

- `ScopusFlowConfigError`, raised before any request when pybliometrics has not been
  initialised in the session, in place of pybliometrics' misleading "No configuration
  file found". `fetch_plan()`, `scopus_count()`, `scopus_trend()`, `compare_topics()`
  and `scopus_abstract()` check before their first request, and the message names the
  configuration file and the call to make. A harvest or an abstract batch resumed
  wholly from its checkpoints sends no request, so it still runs without `init()`.
  scopusflow never calls `pybliometrics.init()` itself.

- `write_records()` and `read_records()`, the twins of the R package's
  `write_scopus_records()` and `read_scopus_records()`, save a record set and read it
  back, the file extension choosing the format. Parquet keeps the provenance
  attributes, stored under the `scopusflow` key of the file's schema metadata so that
  they survive whatever the pandas version. CSV keeps the columns, read back with the
  record schema imposed, so `scopus_id` stays text and `year` and `citations` stay
  whole numbers. Parquet needs pyarrow, which the new `parquet` extra installs.
  `SearchPlan.to_dict()` and `SearchPlan.from_dict()` turn a plan into a plain dict and
  back.

- `fetch_plan()` gains `cursor`. Left unset, or `True`, it keeps the cursor paging
  `fetch_plan()` has always used. `cursor=False` pages by offset, the route
  pybliometrics documents for keys without a Scopus subscription. Offset paging
  cannot retrieve a cell that matches more than 5000 records, and pybliometrics
  refuses such a cell with `ScopusQueryError`, which `fetch_plan()` now raises again
  with the cell named and the remedies given. The checkpoint manifest records the
  paging mode, so a checkpoint is served only to a harvest in the mode it was fetched
  under, and one without a manifest counts as paged by cursor. A checkpoint in the
  other mode is refetched with a warning that names both modes. The search record's
  reproduction snippet adds `cursor=False` when the records were paged by offset.
  The R twin's `scopus_fetch_plan()` gains `cursor` as well, defaulting to the
  offset paging its plans have always used.

- `fetch_plan()` and `to_records()` gain `fields="extended"`, adding the document
  type, source type, volume, issue, pages, ISSN, PubMed identifier and open-access
  status the Search API already returns, and the abstract under the `COMPLETE` view,
  at no extra quota. `EXTENDED_COLUMNS` names the columns both views add. CSV
  checkpoints and `read_records()` read them with the record schema imposed, as text
  apart from the whole-number `open_access`, so an ISSN keeps its leading zeros. Each
  checkpoint manifest records its fields. An extended harvest refetches a checkpoint
  that lacks the extended columns and warns that it did. An extended checkpoint
  serves a core harvest with those columns dropped. The default,
  `fields="core"`, returns the columns it always has. The R twin's
  `scopus_fetch()`, `scopus_fetch_plan()` and `scopus_records()` gain `fields` too,
  and its `summary()` reports how many records Scopus labels errata or retracted.

- With `fields="extended"`, `to_ris()` and `to_bibtex()` type conference papers,
  conference reviews, chapters and books by the document type Scopus gives them (RIS
  `CPAPER`, `CONF`, `CHAP` and `BOOK`, BibTeX `@inproceedings`, `@incollection` and
  `@book`), where every record used to be a journal article. The entries carry the
  volume, issue, pages, ISSN and document type, and under `view="COMPLETE"` the
  abstract, which screening and de-duplication tools read. A `COMPLETE` set also
  exports its author keywords, one RIS `KW` line each, with or without the extended
  fields. A value the record lacks is left out. The R twin's `as_ris()` and
  `as_bibtex()` do the same, held to a shared golden file.

- `scopus_abstract(include=("index_terms",))` returns the index keywords Scopus
  assigns, read from pybliometrics' `idxterms` into an `idxterms` column joined with
  `"; "`, under `view="FULL"`. `corpus()` can use them, alone or with the author
  keywords, through its new `keywords` argument, `"index"` or `"both"`, and raises
  `ValueError` for either under `view="REF"` before any request. The default,
  `keywords="author"`, keeps the author keywords alone. Scopus chooses index keywords
  from standard vocabularies, so they give different co-occurrence results from author
  keywords, and whether they arrive depends on the key's entitlement. An index term
  pybliometrics cannot parse leaves that document's index keywords NA with a warning
  and keeps the rest of its row. The R twin's `scopus_abstract()` and
  `scopus_corpus()` gain the same options.

- `write_corpus()` writes a `corpus()` result in theoryforge's corpus schema, keying
  cited works on the Scopus identifier so the same work is one node however its DOI is
  written. `to_theoryforge_corpus()` returns the same document as a dict. A reference
  that carries only a DOI takes the identifier that another document or reference in
  the corpus pairs with that DOI, and one with neither is dropped with a warning.
  Keywords are trimmed, lower-cased and made unique, and a missing year is written as
  `null`, whether it is `None`, `NaN` or `pd.NA`. Keyed on the DOI wherever there was
  one, as theoryforge's own recipe did, two documents citing the same two works gave no
  co-citation edge. A `provenance` block records the search expression, when the
  search ran, the kind of keyword and how many references were dropped and records came
  without keywords. The writer never imports theoryforge. The R twin's
  `write_scopus_corpus()` and `as_theoryforge_corpus()` write the same bytes, held to a
  shared golden file, which the tests validate against a copy of theoryforge's schema.
  The `dev` extra gains `jsonschema` for that check.

- `diff_records()` compares two harvests record by record, matching on the Scopus
  identifier and, where a record lacks one, on the DOI, as `scopus_combine(dedupe=True)`
  matches records. Each row gives the record's citation counts in both harvests beside
  its status, identifier, DOI, title and year. A record in one harvest only whose DOI the
  other harvest gives to a different record is marked `conflict` for you to check, since
  it may have been re-indexed under a new identifier or may be a distinct paper sharing
  the DOI. Records with neither key are counted in `attrs` and left out. The R twin's
  `scopus_diff_records()` returns the same rows, held to a shared fixture.

### Changed

- `corpus()` returns each document's Scopus identifier in a new `scopus_id` column,
  the second, as the R twin's `scopus_corpus()` now does. It comes from Abstract
  Retrieval, or from the records where the lookup failed. Code that selects the
  corpus's columns by position needs updating. The R twin's corpus now reports the
  requests it made and the quota left, as this one always has. The result's `attrs`
  also carry the search expression, when the search ran and the kind of keyword, as
  `query`, `retrieved_at` and `keywords`, which `write_corpus()` records.

- `CITATION.cff` names PyPI as the package's repository artifact, as the R
  twin's names CRAN, and says that its DOI is the Zenodo concept DOI of this
  repository, which holds the Python package alone, since PyPI assigns no DOI.
- The home page gives the Zenodo concept DOI as a full link,
  <https://doi.org/10.5281/zenodo.21252666>, in place of the Zenodo badge, and
  the About page links every DOI the same way, so its reference line can be
  clicked. The BibTeX entry's `url` gives the PyPI page, so a style that prints
  both fields no longer shows the DOI twice. The README's DOI badge now ends the
  badge row and names the DOI in its text alternative.
- `fetch_plan()` attaches the per-cell accounting as `attrs["cell_totals"]` (`cell`,
  `date`, `n_records`, `reported_total`), and `attrs["total_results"]` is now the sum
  only when every cell reported a total, `None` otherwise. It previously summed the
  cells that happened to report one, which understated a search while looking like a
  real figure. The harvest also carries its originating `plan`, `retrieved_at`,
  `scopusflow_version` and `paging`, matching the attributes the R twin records. The
  time and version are omitted when any cell was resumed from a checkpoint written
  before checkpoints carried a manifest, since such a checkpoint has no record of when
  it was taken.

- A harvest resumed from manifest-backed checkpoints keeps each cell's reported total,
  retrieval time and version, as the R twin does, so its search record states the date
  and completeness. The time is the earliest cell's, and the version becomes a sorted
  list when the cells were fetched by more than one release. The version is now
  claimed whenever every cell supplies one, as in the R twin, where it used to be
  dropped with the time.

- `fetch_plan()` stores its provenance in JSON-safe forms: `attrs["plan"]` is a dict
  (`SearchPlan.from_dict()` rebuilds the plan), `attrs["retrieved_at"]` an ISO 8601 UTC
  string to the second and `attrs["cell_totals"]` a list of dicts.
  `scopus_search_report()` and `scopus_combine()` read these forms and the
  `SearchPlan`, `datetime` and DataFrame values a guide sets by hand.

- The minimum `pybliometrics` is now 4.4, raised from 4.0. The reference-shaping code
  imports the `Reference` namedtuple from `pybliometrics.scopus`, which no release
  before 4.4 provides, so 4.0 through 4.3 installed without complaint and then
  raised `ImportError` on the first call that touched references. The floor now
  states what the code actually needs.

- The app extra's minimum NiceGUI is now 2.14, raised from 2.0. Every in-browser
  export goes through `ui.download.content`, which NiceGUI gained in 2.14.0, so 2.0
  through 2.13 installed without complaint and then raised `AttributeError` on the
  first download click. The reasoning is the same as for the `pybliometrics` floor:
  state what the code needs.

- `scopusflow-gui` accepts `--version`, `--host`, `--port` and `--no-browser`, and
  rejects an unknown flag where it used to ignore one. The console-script target moved
  from `scopusflow.app:launch` to `scopusflow.app:main`, so an existing editable install
  needs reinstalling for the flags to take effect.

- `TREND_COLUMNS`, `COMPARISON_COLUMNS` and `ABSTRACT_COLUMNS` are exported from the
  package top level alongside `RECORD_COLUMNS`, making the API page's importability claim
  true. CITATION.cff no longer credits this package with rate-limit handling, which only
  the R twin implements. The Python 3.14 classifier is declared, matching the matrix.

- The app's reproducible script records the package version and, in demo mode, states
  that the records were replayed from the bundled harvest.

- The documentation's five reference pages are now one grouped API reference at
  `/api/`, which is how the other Python packages in the family present theirs. The
  groups and their order are unchanged, so a function still sits under the heading the
  R twin files it under, and each old page URL redirects to the merged page and carries
  any anchor across with it.

- The changelog, CITATION.cff and the documentation no longer present 0.4.0 as
  released, since PyPI carries 0.3.0. The documentation header shows the newest
  released version, read from the git tags when the site is built, and the site is
  rebuilt when a release is published. A banner marks pages built from a development
  version, and the About page takes the version it cites from CITATION.cff. The
  publish workflow refuses a release unless its tag, `__version__`, CITATION.cff and
  the README's citation name one version, and CITATION.cff and the changelog are
  dated the day it is published.

- Packaging: the build backend is no longer held below hatchling 1.32, whose metadata
  version twine now accepts, and the licence is declared once, as an SPDX expression,
  without the classifier PEP 639 deprecates.

- Queries are checked offline before any request. `LIMIT-TO()` and `EXCLUDE()`
  refinement syntax pasted from the web interface, a field tag wrapped around a query
  that already opens with one, and unbalanced brackets, quotation marks or braces now
  raise `ValueError` in `SearchPlan`, `scopus_count()`, `scopus_trend()`,
  `compare_topics()` and `scopus_intersections()`. The Search API ignores a refinement
  without an error, so such a search ran unfiltered. A nested field tag failed with
  HTTP 400 after spending a request, and unbalanced brackets reached the API
  unchecked. `INDEXTERMS()`, which pybliometrics documents as not working through the
  Search API, issues a `scopusflow.query.QuerySyntaxWarning`, a `UserWarning`. The
  messages match the R twin's word for word. `wrap_field()` raises on a query that
  already opens with a field tag, and so does `scopus_query()` given a `field`.
  `scopus_intersections()` uses a concept written as the web interface writes a tag,
  `TITLE-ABS-KEY ( x )`, as given, where it used to wrap it in `field` a second time.

- The documentation no longer attributes truncated REF reference lists to the API.
  REF serves about 40 references per request, and pybliometrics pages REF itself, so
  `scopus_abstract(view="REF")` and `corpus(view="REF")` return the whole list at a
  cost of one request per 40 references. `n_requests` counts each document once,
  however many pages pybliometrics requested for it. The truncation the guides
  described came from the R twin, which requested only the first page and now follows
  the rest.

- The guides now show `pybliometrics.init()`, which pybliometrics 4 requires in every
  session, before the first live call. They used to imply that a configuration file
  was enough. The app's generated script calls `pybliometrics.init()` too, where its
  comment suggested `pybliometrics.init(keys=[...])`, which invites pasting the key
  into the script.

- RIS records put the source title under `T2`, which reference managers read as the
  publication title, instead of `JO`, which Zotero reads as the journal abbreviation,
  and now carry `DB  - Scopus` and the EID as `AN`.

- The guides no longer present the bundled corpus as the result of the unquoted
  search they show. The corpus came from OpenAlex's exact-phrase search for "graphene
  supercapacitor" in titles and abstracts, limited to journal articles. Scopus joins
  the words of an unquoted phrase with AND, so the unquoted search is far broader, and
  in OpenAlex the unquoted words match about a hundred times as many records. The
  demonstration plan and the live harvests beside the corpus now quote the phrase, and
  the `scopusflow.data` docstring names the query the guides send. The tracking guide
  says that a live comparison needs an earlier harvest of your own, since the bundled
  corpus came from OpenAlex. The PRISMA-S demonstrations label their hand-set
  attributes, the reported totals among them, as illustrative and say that the
  paragraph they print describes no search that was run.

- De-duplication in `scopus_combine()` now cleans DOIs as `extract_dois()` does
  (resolver prefixes, case) and matches a record without a Scopus identifier to the
  identified record carrying the same DOI. Records with different identifiers and one
  DOI are still both kept, since Scopus also gives one DOI to distinct papers, and the
  merge now counts them for you to check. `attrs["combined"]` records the rule as
  `rule` and the DOIs such records share as `doi_conflicts`, and PRISMA-S item 16 of
  the search record names the rule and gives the count. `dedupe="id_or_doi"` merges
  records with different identifiers that share a DOI, and `dedupe="id_then_doi"`
  reproduces the earlier rule. A set merged before records no rule and keeps its item
  16 wording. `dedupe` raises `ValueError` for anything but a bool or the name of a
  rule, where any truthy value used to de-duplicate. The R twin's `scopus_combine()`
  applies the same rules, and both are held to a shared fixture.

### Fixed

- The search record downloaded in demo mode gave the bundled corpus's own phrase as
  the expression searched, in a methods paragraph written to be pasted into a
  manuscript. The replayed records now reach the report without a query, so the
  expression is unrecorded like the retrieval time beside it, and the file opens by
  saying that the records were replayed and that it describes no search that was
  run. Where the records came from is fixed when the harvest starts, so switching
  Demo mode afterwards does not change the record. The R twin's app does the same.

- The year limit was appended to the query without brackets, so a query with a
  top-level OR or AND NOT was regrouped by Scopus's operator precedence. Under the
  documented order, which applies AND NOT last, `A AND NOT B AND PUBYEAR IS 2015`
  reads as `A AND NOT (B AND PUBYEAR IS 2015)`, and each year cell returned records
  from every year. A check against the live API on 2 October 2026 found 19,510
  records for `TITLE("working memory") AND NOT TITLE(children) AND PUBYEAR > 2020`,
  against 5,454 with the first two operands in brackets. Under the order Elsevier has
  announced for 2026 (AND NOT, AND, OR), a top-level OR loses the limit instead.
  `fetch_plan()`, `scopus_count()`, `scopus_trend()`, `compare_topics()` and
  `scopus_intersections()` now put such a query in brackets before adding the year.
  A query without those operators is sent exactly as before, so its checkpoints and
  its pybliometrics cache stay valid. Re-run any affected harvest, count, trend,
  comparison or intersection. The checkpoints of an affected plan are fetched again
  once, under the existing "different plan" warning.
- `compare_topics()` joined the reference and each term without brackets, so an AND
  NOT reference took the term into its negation, the comparison set outgrew the
  reference and shares could pass 100%. Each comparison query is now
  `(reference) AND (term)`, the form `scopus_intersections()` already used. The R twin
  carried the same defect and was fixed with it.
- `scopus_query()` now brackets each term of several words when it joins two or more
  terms without a field tag, since Scopus joins the words of an unquoted term with
  AND. `scopus_query("machine learning", "deep learning", op="OR")` used to give
  `machine learning OR deep learning`, which reads as
  `machine AND (learning OR deep) AND learning`. Quoted and braced phrases, bracketed
  groups and single field-tagged groups are left as written, and single words are
  never bracketed. The R twin carried the same defect and was fixed with it.
- Searches could be answered from pybliometrics' own on-disk cache without
  contacting the API. pybliometrics keys that cache on the query string and view
  alone and serves from it unless `refresh` is True, and scopusflow never passed
  `refresh`. A re-run of `fetch_plan()` into a fresh `cache_dir` therefore returned
  the first pull, dated now, with the cached row count standing in for the API's
  total. That silenced the shortfall check, and the change-tracking workflow
  compared a harvest with itself. `scopus_count()`, `scopus_trend()`,
  `compare_topics()` and `scopus_intersections()` could return the number of rows an
  earlier harvest of the same query left in the cache, and a comparison could set
  such a reference against fresh counts, giving shares above 100%. scopusflow now
  passes `refresh=True` unless you pass `refresh` yourself, so a re-run spends
  quota, as the guides said it did. Pass `refresh=False`, or a number of days, to
  opt in to pybliometrics' cache. A harvest cell served from it is then dated by
  the cache file and has no reported total, and every answer taken from it comes
  with a warning.
- `scopus_abstract()` checks its identifiers before any request. A missing or blank
  one now raises `ValueError` naming its position, and a value that is neither text
  nor a whole number, such as a float, raises `TypeError`. pybliometrics used to
  request `None` as the DOI `"None"` and `pd.NA` as `"<NA>"`, and with `cache_dir`
  the batch stopped on a `TypeError` at the same identifier on every resume. Whitespace is
  trimmed and the `SCOPUS_ID:` prefix dropped, as in the R twin, and whole-number
  Scopus IDs are sent as text. `corpus()` drops blank identifiers along with missing
  ones. `n_requests` counts each request once, where a step failing after the
  response arrived counted it twice, and it no longer counts rows pybliometrics read
  from its own cache. A keyword entry pybliometrics 4.4.1 cannot parse (its issue
  436) leaves that document's keywords NA with a warning, where it discarded the
  whole row. `include=("keywords",)` now requires `view="FULL"`, since under the
  other views it gave a silently empty column, and `corpus(view="REF")` requests
  references only, as the R twin does.
- `scopus_combine()` raised on two harvests, and mixed them up when it did not.
  `concat` decides whether to hand the inputs' `attrs` to the result by comparing the
  dicts, and two `fetch_plan()` harvests each carry a `cell_totals` frame, so the
  comparison ended up evaluating one frame against another and pandas raised "The truth
  value of a DataFrame is ambiguous". Where it did succeed, because the inputs happened
  to carry the very same objects, the union inherited one harvest's `plan`,
  `total_results` and `cell_totals`, and the search record then reported two harvests as
  complete against a total belonging to one of them. The merged set now drops the
  `plan`, `total_results` and `cell_totals` of its inputs, as the R twin's does, and
  records the merge counts.
- `scopus_combine()` keeps what a merge does not invalidate: the earliest of the
  inputs' retrieval times, every contributing scopusflow version and the paging mode
  where the inputs agree, each only when every input carries it. A search record
  written from a merged set said the date searched, the software and the paging mode
  were unrecorded, where the R twin's record of the same inputs states them.
- The PRISMA 2020 identification block counted the records identified after
  de-duplication, so the two figures it gives could not both be right: the diagram
  subtracts the duplicates removed from the records identified to reach the records
  screened, and 138 identified less 11 removed is not the 138 rows the set holds. Where
  a merge recorded how many records went into it, that is now the identification count.
  The R twin carried the same defect and was fixed with it.
- A plan not yet run was described in the past tense, and its date line said the set
  did not carry a retrieval time, when the truth was that no retrieval had happened.
- `SearchPlan` kept its years in the order they were typed, so two plans describing
  the same search compared unequal, and the reproduction snippet
  `scopus_search_report()` emits, which renders them canonically, rebuilt a plan that
  ran identically but failed an equality check against its own original. Years are now
  stored sorted and de-duplicated, as every other caller of the year check already
  treated them and as `cells()` already did with them.
- A missing value became the literal string `"nan"`. An absent EID landed in
  `scopus_id` as the four characters `nan`, which every later guard then accepted as a
  perfectly ordinary identifier, and a missing citation count raised where it should
  have yielded NA. Both paths, search and abstract, now test for missingness before any
  string coercion.
- Resuming from a CSV checkpoint changed the identifiers. `scopus_id`, `year` and
  `citations` were float-promoted on read, so a resumed record exported an identifier
  that differed from the one it was harvested with.
- The comparison average summed its numerator over years its denominator excluded, so
  a year with no reference count inflated it above every per-year share printed beside
  it, and that average orders the topics in the plot. It is now computed over the years
  where both counts are present. The R twin carried the same defect and was fixed with
  it.
- Checkpoints are written atomically, and a damaged one is recoverable. Both the
  per-cell harvest cache and the per-identifier abstract cache wrote straight at their
  destination, so an interrupted run left a half-written file that raised out of the next
  resume and blocked it permanently. Each now writes to a sibling temporary file and
  renames it into place, and a checkpoint that cannot be read back is discarded with a
  warning and refetched. The warning text is byte-identical to the R twin's. That last
  guard only worked for parquet: a truncated CSV is still a well-formed CSV, and a row
  wider than its header does not raise either, because pandas reads the surplus field as
  an index and returns a tidy frame. A damaged CSV checkpoint was therefore parsed into
  whatever it happened to look like and merged into the results. A checkpoint must now
  also carry every `RECORD_COLUMNS` name to be accepted, `authkeywords` aside, since a
  checkpoint written before that column existed simply predates it, and is
  accepted as such.
- A short harvest passed unnoticed. `fetch_plan()` now compares each cell against the
  total the API reports for that cell's query, warns on a shortfall, and attaches the
  summed total as `result.attrs["total_results"]`.
- Year validation now matches the R twin. Non-whole, out-of-range and non-numeric
  years are refused at every entry point, where they used to be silently truncated or
  interpolated into the query. Note this newly refuses numeric strings such as `"2015"`,
  which the R half has always rejected.
- `corpus()` carries through `scopus_abstract()`'s request and quota accounting, where
  it used to discard it, and `plot_top()` raises a named error on an empty tally like
  its sibling plots.
- A transient failure was checkpointed as data. `scopus_abstract()` wrote the all-NA
  row a failed retrieval records into the per-identifier cache, so a timeout, a quota
  refusal or a server error became permanent cached data that every later resume read
  back in place of the real record. Only successful retrievals are checkpointed now, and
  a failed identifier still yields its warned-about NA row and is retried on the next
  resumed run. The R twin carried the same defect and was fixed with it.
- A quota lookup could turn a successful retrieval into an NA row. The quota block in
  `scopus_abstract()` guarded `get_key_remaining_quota` but called
  `get_key_reset_time()` unguarded, so an object exposing only the first failed the
  whole row after the retrieval had already succeeded. Both lookups are now optional.
- Resuming a `COMPLETE`-view cache under a `STANDARD` plan returned `authkeywords`,
  a column the documentation says `STANDARD` output never carries. The checkpoint plan
  check now compares the view as well as the query, and a mismatched checkpoint is
  warned about and refetched in either direction. New checkpoints record the view they
  were written under (stripped again on resume), and a checkpoint from before
  `authkeywords` existed is still accepted under `COMPLETE`, since it predates the
  column and so cannot be foreign.
- Closing one app tab deleted every session's checkpoints. The GUI's disconnect
  cleanup removed the shared temp base, one level above its own directory, so a second
  tab's harvest lost its cache mid-run. Each page scope now works under a per-session
  subdirectory and removes only that when its tab closes.
- The app's generated script downloads as `scopusflow-script.py`, matching the R twin's
  `scopusflow-script.R`. Saved as `scopusflow.py` and run from the folder it was saved
  in, it imported itself under the package's name and stopped with an AttributeError.
- Under `view="COMPLETE"` the authors are joined by `"; "`, as in the R twin, where
  pybliometrics' bare `";"` was kept, so the R twin read a list written here as one
  author. An author whose given name is null or empty is now the surname alone, where
  pybliometrics' `"Surname, "` left a trailing comma. Under `STANDARD` the column holds
  the first author, the API's `dc:creator`, and `top(by="author")` now says so with a
  warning, once per process. Harvests record `attrs["view"]`, which `scopus_combine()`
  keeps where its inputs agree. A `COMPLETE` checkpoint written before the change has
  its authors joined as it is resumed, at no extra request.
- `SearchPlan` normalises and validates `field` when it is built, as the R twin does:
  `" title-abs-key "` is stored as `"TITLE-ABS-KEY"`, and an invalid tag or a
  non-string raises `ValueError` at construction, where it used to fail at first use.
  Stored as passed, the tag sent the same query as the canonical one but compared
  unequal to it, and the search record and its reproduction snippet printed it raw.
- A `fetch_plan()` harvest could not be saved with `DataFrame.to_parquet()`, and
  `merge`, `groupby(...).apply` and `concat` on it raised "The truth value of a
  DataFrame is ambiguous", because its attributes held a `SearchPlan`, a `datetime`
  and a DataFrame. pandas 2.1 and later write `attrs` as JSON when saving to parquet,
  and pandas compares the inputs' `attrs` in those operations. The tracking guide
  recommended `to_parquet` for keeping a baseline, and its CSV alternative lost the
  provenance and read `scopus_id` back as a number, or as a float once one identifier
  was missing, after which a de-duplicating `scopus_combine()` matched none of the
  baseline's records. The guide now uses `write_records()` and `read_records()`.
- `to_bibtex()` and `to_ris()` wrote Scopus's "Surname I." names without a comma, so
  BibTeX and biber took the initials for the family name and sorted bibliographies by
  them, and Zotero kept each RIS author as a single field. This touched every
  `STANDARD`-view export, since that view's names come from `dc:creator`. A name ending
  in initials is now written "Surname, I.", and BibTeX titles protect words such as
  CRISPR-Cas9 and DNA from lower-casing. BibTeX also spaces run-together initials
  ("J. R."), which it would otherwise read as one given name. The `authors` column and
  the citation keys are unchanged. The rule matches the R twin's, held to the shared
  fixture `tests/fixtures/author-names.json`.
- A checkpoint holding no records was served to any plan pointed at the same
  `cache_dir`, because the guard compared the query recorded in the rows and an empty
  cell has none. A plan whose early years were empty could hide a populated year behind
  another plan's empty one, and shifting a reused plan's years did the same. Each
  checkpoint now has a manifest, `cell-NNN.json`, recording the query, view, page size
  and paging it was fetched under, which resume compares. Empty checkpoints written by
  earlier versions are refetched once, with one warning for the harvest.
- `scopus_abstract()` stops at a spent quota (pybliometrics' `Scopus429Error`, which
  it raises once every configured key has been refused) and returns the rows already
  retrieved, with an NA row for each identifier not retrieved and one
  `ScopusFlowQuotaWarning`, a new `UserWarning` subclass exported from `scopusflow`.
  Each remaining identifier used to be requested and become an NA row with a warning
  of its own. `corpus()` inherits the stop. The R twin stops in the same way on a 429
  marked `QUOTA_EXCEEDED`.
- A caller's `subscriber=False`, pybliometrics' documented switch for keys without a
  Scopus subscription, was silently overridden, because `fetch_plan()` always sent
  `cursor=True` too and pybliometrics lets that alias win. Passing `cursor=False`
  raised `TypeError`. `fetch_plan()` now sends `subscriber` alone, set from `cursor`
  or from the caller's `subscriber`, and refuses the two when they disagree. The
  guides gave the offset ceiling as the reason to partition a plan by year, although
  `fetch_plan()` pages by cursor. They now say that the partition gives per-year
  checkpoints, completeness checks and progress. Under offset paging, it also keeps
  each cell within the 5000-record ceiling.
- The search record dated a harvest by its earliest cell, although PRISMA-S item 13
  asks for the date of the last search. `fetch_plan()` now records the latest of its
  cells' times as `attrs["retrieved_until"]`, beside the earliest in
  `attrs["retrieved_at"]`, and `scopus_combine()` keeps both for a merged set, the
  latest of its inputs' times beside the earliest, as the R twin does. A search run
  over several sessions, or a baseline merged with its update, is now dated from its
  first retrieval to its last, item 13 gives the date of the last search, and the
  methods paragraph says the literature was searched between the two dates. Stamps on
  one UTC day give the single date they always gave.
- A set without a plan no longer says "no year limit" when its limit is only
  unrecorded, and no longer lists item 8 of PRISMA-S as supplied. A one-cell plan
  supplied for a set without per-cell counts keeps the set's own counts, as the R
  twin's record does. Year cells with gaps between them are listed, as in "2015,
  2020 and 2025", where the record gave one span that claimed the years between.
  Item 2, on databases searched together on one platform, is now supplied, since
  the API searches Scopus alone.
- The docstrings of `scopus_count()`, `SearchPlan` and `scopus_intersections()` now
  say how `years` is sent. A count, an intersection and a plan with
  `partition="none"` send one inclusive range from the earliest year to the latest,
  so `[2015, 2020]` covers every year from 2015 to 2020. `scopus_trend()`,
  `compare_topics()` and a plan with `partition="year"` take each listed year.
- A harvest stopped through `should_stop` (the app's Cancel) was written up as fully
  run, with the per-cell totals it had recorded discarded. The record now says how
  many cells ran before the stop, which years they covered and that the harvest is
  incomplete, and marks the cells it never reached "not run". `fetch_plan()` records
  the stop as `attrs["stopped_early"]`, with `attrs["cells_planned"]` and
  `attrs["cells_run"]`, and gives a stopped harvest no `total_results`. The app
  announced such a harvest as "Retrieved N records." and now warns "Stopped after k
  of N cells.", in demo mode too. A frame carrying the R twin's `max_results`
  attribute is described as capped, as the R record describes it.
- The script the app writes passed `cache_dir='harvest'` for every plan, so one plan's
  checkpoints overwrote another's and each rerun paid for them again. Each plan now gets
  a directory of its own, `harvest-` followed by eight hexadecimal digits drawn from the
  query, the years, the field, the view and the partition, so running the same script
  again resumes. A comparison run with Partition by year off, which covers the last six
  years, was left out of the script and is now written over those years. The API
  reference gave a comparison's cost as one count request per term per year. It is
  (terms + 1) × years, since the reference is counted in every year too, as the app's
  own note already said. The app guide no longer says that a quota-limited run picks up
  where it left off, since the app removes its checkpoints when the tab closes, and
  points to the generated script for a harvest that has to outlast the session. The R
  twin's script and app had the same faults and were fixed with them.
- `diff_dois()` now says how many records it could not compare for want of a DOI, in
  `attrs["n_old_without_doi"]` and `attrs["n_new_without_doi"]`. Such records used to
  vanish from the diff without a count. The tracking guide gave its 43 added and 83
  unchanged DOIs as the papers new since the baseline and present in both pulls, which
  number 44 and 93. It now gives both counts and says that the records without a DOI
  were not compared. The R twin's `scopus_diff_dois()` now orders its rows in byte
  order, as this one does, where it followed the locale's collation.
- A `cache_dir` that cannot be written is now refused with `ValueError` before any
  request, in `fetch_plan()`, `scopus_abstract()` and `corpus()`. A checkpoint or
  manifest that cannot be written all the same, for example on a full disk, is warned
  about, and its records are kept in the result. A directory that could not be written
  used to spend the cell's requests and then lose its records to an `OSError`, and a
  file given as `cache_dir` raised `FileExistsError`.

### Security

- The app wrote a pasted API key in plain text to `~/.config/pybliometrics.cfg` on a
  machine without a pybliometrics configuration, contrary to its own documentation. It
  now keeps the key in memory and, when no configuration exists, gives pybliometrics a
  key-less one in a temporary directory removed when the app stops. Responses are
  cached there too, so none outlive the app. With a configuration of your own, the app
  uses it without adding the pasted key, and responses go to the cache it names, where
  they stay after the tab closes.

## [0.3.0] - 2026-07-23

### Added

- `example_records()` returns a bundled worked-example harvest of 138 real
  journal articles on graphene supercapacitors, 2015 to 2024, over the standard
  `RECORD_COLUMNS` schema. The records come from OpenAlex, whose metadata is
  released under CC0; Scopus terms do not permit redistributing retrieved
  records. They are the same corpus the R twin ships.

### Changed

- Every guide and reference example now runs on that bundled harvest, where a
  fabricated frame used to stand in, with the live API call shown alongside. The
  app's demo mode replays it too, so a first visit shows real articles and a real
  publication curve. A demo cell for a year outside the corpus returns nothing and
  says so in the log, since padding it out with a neighbouring year's rows would
  double records up. The app's year slider opens on the corpus span, and the demo
  comparison, whose counts are still simulated, now says so beneath the figure.

### Fixed

- `extract_dois` no longer emits the literal `<NA>` for a record with no DOI,
  which a nullable string column produces where a float NaN would have been
  skipped.

## [0.2.0] - 2026-07-15

### Added

- Concept intersections: `scopus_intersections` sizes a named set of concepts
  and their overlaps from the count endpoint (one cheap request per row, no
  harvest), accepting bare terms wrapped in a field tag or complete field-tagged
  expressions used as given, with optional short labels for the intersection
  rows. `plot_scopus_intersections` draws the result as a log-scale lollipop
  chart with a focal set accented. This brings the Python package to parity with
  the R `scopus_intersections()` and `plot_scopus_intersections()`.

## [0.1.0] - 2026-07-10

First release: a reproducible workflow layer over
[pybliometrics](https://pybliometrics.readthedocs.io) for Scopus searches, and
the Python twin of the R package
[scopusflow](https://pablobernabeu.github.io/scopusflow/).

### Added

- Search planning and queries: `SearchPlan` describes a search before running
  it and can be partitioned by year, a field-tagged boolean query builder
  (`scopus_query`, `wrap_field`) with a reference table of Scopus field tags,
  and cheap result-size lookups (`scopus_count`) for quota-aware pre-flight
  sizing.
- Harvesting: resumable, checkpointed retrieval of a plan (`fetch_plan`), with
  per-cell progress logging on the `scopusflow` logger and co-operative
  cancellation (`should_stop`). Checkpoints are keyed by the whole plan, and on
  resume the recorded query is compared against the cell's, so a cache
  directory written by a different plan is refetched with a warning rather
  than silently reused.
- Records: one stable, tidy record schema across query types (`to_records`,
  `RECORD_COLUMNS`), with an `authkeywords` column added when
  `SearchPlan(view="COMPLETE")` is used, at no request cost beyond that view's
  own smaller page size.
- Abstract retrieval: batch, per-identifier-resilient `scopus_abstract`
  (default `view="META_ABS"`, so a plain call returns the abstract text), with
  `include=("references", "keywords")` for a document's own reference list and
  author keywords, per-identifier caching keyed by view and `include`
  selection (`cache_dir`/`resume`), `n_requests`/`quota` accounting, a warning
  when the references returned fall short of the document's reported
  `refcount`, and a clear `ScopusFlowForbiddenError` on an entitlement 403
  that stops the batch, suggesting the other of `"FULL"`/`"REF"` only when the
  refused view was one of those two.
- Corpus assembly: `corpus` combines a search result with abstract retrieval
  into a minimal `id`/`title`/`year`/`keywords`/`references` shape for
  downstream tools such as keyword co-occurrence or citation-network analysis,
  covered by the *Author keywords and references* guide.
- Trends and comparison: annual publication trends (`scopus_trend`,
  `year_counts`) computed from cheap result-size lookups, and topic-trend
  comparison (`compare_topics`) with per-step progress logging. The
  comparison's documented count-request cost includes the reference topic:
  (terms + 1) x years.
- Summaries and change tracking: source and author top tallies (`top`), DOI
  extraction and change tracking between runs (`extract_dois`, `diff_dois`).
- Plots: brand-themed matplotlib figures for trends (`plot_trend`), top
  tallies (`plot_top`, labelling each bar with its count and reserving x-axis
  headroom so the longest label stays inside the axes) and topic comparison
  (`plot_comparison`, mirroring the R `plot_scopus_comparison`): illustrative
  Wilson stability bands with a Source/Wilson caption, a percent-formatted
  y-axis, record counts in the labels by default (`counts_in_legend`), the
  reference topic named in a subtitle, colour-matched end-of-line labels
  spread apart at draw time in the same order as the line ends, an optional
  `legend_inside` placing the legend in the emptiest corner, and full schema
  validation with a friendly `ValueError`.
- Reference-manager export to BibTeX and RIS (`to_bibtex`, `to_ris`), so a
  search carries into Zotero, EndNote, Mendeley or a LaTeX bibliography.
- A local, code-free NiceGUI app (`scopusflow-gui`, the `app` extra) that
  drives the whole workflow through a browser tab: a background harvest with a
  live progress terminal, every choice (including the chosen `view` and the
  comparison) mirrored back as a runnable Python script, results shown as a
  paginated table and plots with export, a Compare topics card with highlight,
  stability-band and counts-in-label controls plus a count-request cost
  estimate and CSV export, and a demo mode that needs no key. Harvest
  checkpoints live under the temp directory and are removed when the tab
  closes, so search terms do not linger on disk. Duplicate comparison terms
  are dropped, a zero-record harvest is reported as a warning, and the
  controls carry visible labels.
- Documentation guides that execute their examples, so tables and plots appear
  inline as on a knitted vignette.

[Unreleased]: https://github.com/pablobernabeu/scopusflow-py/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/pablobernabeu/scopusflow-py/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/pablobernabeu/scopusflow-py/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/pablobernabeu/scopusflow-py/releases/tag/v0.1.0
