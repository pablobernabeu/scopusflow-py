# The code-free app

Not every search starts in an editor. scopusflow ships a local [NiceGUI](https://nicegui.io) app that drives the whole workflow through a browser tab, from describing a search to exporting the records, without writing any Python. It runs on your own machine, so your Scopus key never leaves it and requests come from your own network. The app is an on-ramp to the library rather than a replacement for it, because it mirrors every choice you make back as a runnable script. Anything you can do in the app you can later do from code, and the script in the panel shows you how.

## Launch the app

The app lives behind an optional extra, so install it with the `app` group and start it with the console script:

```bash
pip install "scopusflow[app]"
scopusflow-gui
```

That opens a tab at `http://127.0.0.1:8080`. If you would rather start it from Python, perhaps to choose a different port, call `launch` from the app module. It is not a top-level export, so reach it through the module:

```python
import scopusflow.app

scopusflow.app.launch(host="127.0.0.1", port=8080, show=True)
```

The app binds to `127.0.0.1` on purpose, so it is reachable only from this machine.

## Try it in demo mode

Demo mode is switched on the first time the app opens, so you can walk the entire flow with synthetic data and no key at all. With it on, the harvest is simulated, the live terminal still streams per-cell progress, the table and plots still render, and the Compare topics card still draws a figure. It is the quickest way to learn where each control lives before you spend any quota.

The window below is the app in demo mode just after a harvest, so everything in it was produced without a key. The search card sits on the left and the reproducible Python panel on the right, with the live terminal, the record count, the paginated table and the two figures filling the area beneath them.

![The scopusflow app in demo mode. The search card on the left holds the API key field, the demo-mode switch, the search terms, the field selector, the year range and the Check plan, Fetch records and Cancel buttons. The Reproducible Python panel on the right shows the generated script and a Download script button. Below them sit the Live terminal expansion, a count of 48 records, a paginated table of titles, years, publications and citations, and two figures: records per year, and the most frequent sources.](../assets/app-window.png)

Demo mode produces records with the same stable [`RECORD_COLUMNS`][scopusflow.records.RECORD_COLUMNS] schema a real harvest returns, so the table, the trend plot and the source plot behave exactly as they will against the live API. When you are ready for real results, paste your Scopus API key into the field at the top and switch Demo mode off. The key stays in the running process and is never written to the generated script.

## Describe and size the search

The left card is where you describe the search. You type your terms, choose which field to search in (title, abstract and keywords by default), and set a year range. Partitioning by year is recommended and switched on by default, because it keeps each cell small enough to stay under the API's offset ceiling, the same reasoning behind a partitioned [`SearchPlan`][scopusflow.plan.SearchPlan] in code.

Check plan sizes the search before you commit to it. In demo mode it reports how many synthetic records it would make. With a real key it runs a single cheap count request, the same one [`scopus_count`][scopusflow.count.scopus_count] performs, and tells you how many records the query matches across how many year-cells:

```python
import scopusflow as sf

# What "Check plan" runs with a real key (needs a configured Scopus key).
sf.scopus_count(
    "graphene supercapacitor",
    years=range(2019, 2025),
    field="TITLE-ABS-KEY",
)
```

That call contacts the Scopus API, so it only returns a number once pybliometrics holds a valid key. In the app the key you paste is used for the session; from a script you would configure it yourself with `pybliometrics.init`.

## Run the harvest with a live terminal

Fetch records starts the harvest. The retrieval runs off the event loop in a background worker, so the tab stays responsive while it works, and the Live terminal expansion streams a line per cell as each one completes. A progress bar tracks how far through the plan the run has reached, and Cancel stops the harvest cleanly after the current cell rather than killing it mid-request, so a real run does not waste the cell it is already paying for.

Under the surface the app builds a [`SearchPlan`][scopusflow.plan.SearchPlan] from your choices and hands it to [`fetch_plan`][scopusflow.fetch.fetch_plan] with a per-query cache directory and resume turned on, so an interrupted or quota-limited run picks up where it left off. The equivalent in a script is:

```python
import scopusflow as sf

# What "Fetch records" runs with a real key (needs a configured Scopus key).
plan = sf.SearchPlan(
    "graphene supercapacitor",
    years=range(2019, 2025),
    field="TITLE-ABS-KEY",
    partition="year",
)
records = sf.fetch_plan(plan, cache_dir="harvest", resume=True)
records.shape
```

When the run finishes, the results area shows the record count, a paginated table of titles, years, sources and citations, and two figures drawn by the library itself, a year trend from [`year_counts`][scopusflow.trend.year_counts] via [`plot_trend`][scopusflow.plots.plot_trend] and the most frequent sources from [`top`][scopusflow.records.top] via [`plot_top`][scopusflow.plots.plot_top].

## Read off the reproducible script

The right-hand card, labelled Reproducible Python, is the part that turns the app into a tutorial. It mirrors every choice you make, the query, the field, the year range, whether you partition by year, the chosen view, and the Compare topics options, and rewrites a runnable script as you go. Change a control on the left and the script updates immediately, so you can see exactly which argument each toggle sets.

The script the panel produces follows the same shape as the planning workflow, building a plan, fetching with a cache so a run resumes, inspecting the result, and saving it:

```python
import scopusflow as sf

# Describe the search as an inspectable, reproducible plan.
plan = sf.SearchPlan(
    "graphene supercapacitor",
    years=range(2019, 2025),
    field="TITLE-ABS-KEY",
    partition="year",
)

# Retrieve, caching each cell so an interrupted run resumes. Configure
# your Scopus key with pybliometrics first: pybliometrics.init(keys=[...]).
records = sf.fetch_plan(plan, cache_dir="harvest", resume=True)

# Inspect the most frequent values and the records per year.
sf.top(records, by="source")
sf.year_counts(records)

# Save the records.
records.to_csv("scopus-records.csv", index=False)
```

The key is never written into the script. The panel leaves a comment noting it comes from your pybliometrics config, so a script you share carries the method but not your credentials. Download script (.py) saves exactly what you see.

## Compare topics

The Compare topics card asks a different question from a harvest. Rather than retrieving records, it measures how a set of sub-topics co-occur with your search over time, as a share of it, with your search terms acting as the reference topic. You enter comma-separated comparison terms, optionally pick one to highlight, and toggle the stability band and whether record counts appear in the legend. Because each term needs one count request per year, the card warns you when the term and year counts multiply into a large number of requests.

![The Compare topics card in demo mode. It holds a comma-separated comparison-terms field reading "machine learning, deep learning", a Highlight topic selector, switches for the stability band and for counts in the label, and a Compare topics button. Beneath them is the resulting figure, showing the share of reference records held by each of the two topics rising from 2021 to 2026, each line labelled at its right-hand end with its record count and drawn inside a shaded stability band. A Comparison (.csv) download button sits at the foot of the card.](../assets/app-compare.png)

In demo mode the comparison is synthesised so you can see the figure offline, with its own progress streamed into the live terminal. With a real key the card calls [`compare_topics`][scopusflow.compare.compare_topics] and draws the result with [`plot_comparison`][scopusflow.plots.plot_comparison], the same figure the library produces:

```python
import scopusflow as sf

# What "Compare topics" runs with a real key (needs a configured Scopus key).
cmp = sf.compare_topics(
    "graphene supercapacitor",
    ["machine learning", "deep learning"],
    years=range(2019, 2025),
    field="TITLE-ABS-KEY",
)
sf.plot_comparison(cmp, highlight="machine learning", interval=True)
```

The highlight option only forwards a topic the plot can actually draw, so a term with no plottable share is quietly left unhighlighted rather than raising. As with the harvest, the comparison contacts the Scopus API and needs a configured key to return real counts.

## Export in one click

Every result the app shows comes with one-click export. The records table offers the frame as CSV, and as BibTeX and RIS for a reference manager such as Zotero or EndNote, drawn from [`to_bibtex`][scopusflow.export.to_bibtex] and [`to_ris`][scopusflow.export.to_ris]. The Compare topics card offers its comparison frame as CSV. None of this needs the API again, because it works on results already in hand:

```python
import scopusflow as sf

# The same export the download buttons perform, on records you already have.
with open("scopus-records.bib", "w", encoding="utf-8") as fh:
    fh.write(sf.to_bibtex(records))

with open("scopus-records.ris", "w", encoding="utf-8") as fh:
    fh.write(sf.to_ris(records))
```

Between the downloaded script and the exported records, a session in the app leaves you with both the data and the code that produced it, ready to drop into the rest of your workflow.
