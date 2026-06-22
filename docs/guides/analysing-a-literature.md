# Analysing a literature

Once records are in hand, scopusflow turns them into the figures a bibliometric study usually needs, all from the one stable schema.

## What is in a record set

[`top`][scopusflow.records.top] tallies the most frequent sources or authors. Author strings that hold several names are split, so each contributor is counted once per record.

```python
import scopusflow as sf

sf.top(records, by="source")
sf.top(records, by="author", n=10)
```

## How a literature grows

[`year_counts`][scopusflow.trend.year_counts] is the offline tally of records per year from a set you already hold. [`scopus_trend`][scopusflow.trend.scopus_trend] instead asks the API for the count in each year without downloading the records, which is far cheaper when all you want is the shape of the growth.

```python
trend = sf.year_counts(records)                         # from records in hand
trend = sf.scopus_trend(q, years=range(2010, 2023))     # cheap per-year counts
```

## Turn it into figures

With the optional `plot` extra installed, the summaries become matplotlib figures.

```python
sf.plot_trend(trend)
sf.plot_top(sf.top(records, by="source"))
```

## Read the fuller record

[`scopus_abstract`][scopusflow.abstract.scopus_abstract] pulls the abstract and fuller metadata for a known identifier, and is resilient to the odd id that fails.

```python
abstracts = sf.scopus_abstract(dois[:10], by="doi")
abstracts[["doi", "title", "year"]]
```
