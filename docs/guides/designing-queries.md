# Designing queries

A retrieval is only as good as the query behind it. This guide shows how to compose correct, field-tagged Scopus queries with [`scopus_query`][scopusflow.query.scopus_query] instead of pasting fragments by hand, where a missing bracket or a mistyped tag quietly returns the wrong records. Everything here is string construction, so it all runs offline without an API key. Each call returns the literal string that the Scopus API would receive, which means you can read a query before you ever spend quota on it.

```python exec="1" session="designing-queries"
import html as _html
import pandas as pd
import scopusflow as sf


def _clean_table(html_table):
    # Drop pandas' own class and header alignment so the theme's table
    # styling (padding, borders, zebra rows) applies instead.
    return (html_table.replace(' class="dataframe"', "")
                      .replace(' style="text-align: right;"', ""))


def out(x):
    if isinstance(x, pd.DataFrame):
        print(_clean_table(x.to_html(index=False, border=0)))
    elif isinstance(x, pd.Series):
        label = x.index.name or "value"
        df = x.rename("count").reset_index()
        df.columns = [label, "count"]
        print(_clean_table(df.to_html(index=False, border=0)))
    elif isinstance(x, list) and all(isinstance(i, str) for i in x):
        print("<pre>" + _html.escape(chr(10).join(x)) + "</pre>")
    else:
        print("<pre>" + _html.escape(str(x)) + "</pre>")
```

```python exec="1" source="material-block" session="designing-queries"
import scopusflow as sf
```

## Field tags decide where to look

A field tag restricts a query to one part of a record, so a search for a topic does not drown in incidental full-text matches. The [`FIELD_TAGS`][scopusflow.query.FIELD_TAGS] dictionary maps the common tags to a short description of what each one searches.

```python exec="1" source="material-block" session="designing-queries"
out([f"{tag:<20} {meaning}" for tag, meaning in sf.FIELD_TAGS.items()])
```

The most generally useful tag is `TITLE-ABS-KEY`, which searches the title, abstract and keywords together. It is broad enough to catch a topic without the noise of a full-text match. Because `FIELD_TAGS` is an ordinary dictionary, you can also check membership before building a query, for example `"AUTHKEY" in sf.FIELD_TAGS`.

## Wrapping a single term

[`wrap_field`][scopusflow.query.wrap_field] applies one tag to one term and is the building block the rest of the API uses. Passing `None` as the field leaves the term untouched, which is the right choice when the term already carries its own tag.

```python exec="1" source="material-block" session="designing-queries"
out(sf.wrap_field("graphene", "TITLE-ABS-KEY"))
out(sf.wrap_field("graphene", None))
```

The tag is upper-cased and validated, so a lower-case or stray entry is normalised or rejected rather than passed through. A tag that contains anything other than letters and hyphens raises a `ValueError`, which catches a typo at the point of construction.

```python exec="1" source="material-block" session="designing-queries"
out(sf.wrap_field("graphene", "title-abs-key"))   # upper-cased to TITLE-ABS-KEY

try:
    sf.wrap_field("graphene", "TITLE_ABS")           # underscore is not allowed
except ValueError as exc:
    print(exc)
```

## One term, many disciplines

[`scopus_query`][scopusflow.query.scopus_query] builds on `wrap_field` and serves any field. Each call below returns the exact query string that would be sent to Scopus, with the `field` argument applied to every term.

```python exec="1" source="material-block" session="designing-queries"
out([
    sf.scopus_query("CRISPR", field="TITLE-ABS-KEY"),               # molecular biology
    sf.scopus_query("gravitational waves", field="TITLE-ABS-KEY"),  # physics
    sf.scopus_query("microplastics", field="TITLE-ABS-KEY"),        # environmental science
    sf.scopus_query("blockchain", field="TITLE-ABS-KEY"),           # computer science
    sf.scopus_query("digital humanities", field="AUTHKEY"),         # humanities
])
```

The last example uses `AUTHKEY`, the author-supplied keywords, which isolates work that self-identifies with a field and so cuts incidental mentions.

## Combining terms with boolean operators

Passing several terms joins them into one query. The default operator is `AND`, and `OR` or `AND NOT` are available through the `op` argument. The same `field` is wrapped around each term before the terms are joined, so the boolean logic stays unambiguous.

```python exec="1" source="material-block" session="designing-queries"
# Two concepts that must co-occur (materials science).
out(sf.scopus_query("perovskite", "solar cell", field="TITLE-ABS-KEY"))

# Spelling variants, either of which will do (economics).
out(sf.scopus_query("behavioral economics", "behavioural economics", op="OR"))

# A family of related tools (molecular biology).
out(sf.scopus_query("CRISPR", "Cas9", "Cas12", op="OR"))
```

An operator outside the permitted set raises a `ValueError`, so `op="NOT"` or a typo is caught before the string is built rather than rejected later by the API.

## Searching by affiliation

Field tags reach beyond topics. `AFFILORG` searches the affiliation organisation name, which turns a query into an institution-level view of output.

```python exec="1" source="material-block" session="designing-queries"
out(sf.scopus_query("Max Planck", field="AFFILORG"))
```

## When a term is empty

The builder validates its input, so a stray empty term is caught at construction rather than producing a malformed query that fails downstream. An empty or whitespace-only term raises a `ValueError`.

```python exec="1" source="material-block" session="designing-queries"
try:
    sf.scopus_query("graphene", "")
except ValueError as exc:
    print(exc)
```

## From a query to a plan

A composed query drops straight into the rest of the workflow. The same string anchors a [`SearchPlan`][scopusflow.plan.SearchPlan], and partitioning by year keeps each cell under the API's offset ceiling. Note that the plan can apply the field tag itself through its own `field` argument, so you pass the bare topic and let the plan wrap it once.

```python exec="1" source="material-block" session="designing-queries"
plan = sf.SearchPlan(
    "gut microbiome",
    years=range(2015, 2023),
    field="TITLE-ABS-KEY",
    partition="year",
)
out(plan.wrapped_query)                            # the string the API will receive
out([(c.cell, c.year) for c in plan.cells()])      # one cell per year
```

Sizing and running the plan both contact the Scopus API, so the two calls below need a key (set `SCOPUS_API_KEY` in your environment or configure pybliometrics) and are the only step here that goes online. [`scopus_count`][scopusflow.count.scopus_count] reports how many records the query matches without downloading them, which is the cheap way to check a search before committing quota to it.

```python
# Both calls require a configured Scopus API key.
sf.scopus_count("gut microbiome", years=range(2015, 2023), field="TITLE-ABS-KEY")
records = sf.fetch_plan(plan)
```
