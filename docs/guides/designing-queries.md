# Designing queries

A retrieval is only as good as the query behind it. This guide shows how to compose correct, field-tagged Scopus queries with [`scopus_query`][scopusflow.query.scopus_query], which spares you pasting fragments together by hand, where a missing bracket or a mistyped tag quietly returns the wrong records. Everything here is string construction, so it all runs offline without an API key. Each call returns the query as a literal string, which means you can read it before you ever spend quota on it. A count, a trend or a harvest sends that string with any year limit appended, as the last section shows.

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
        print("<pre><code>" + _html.escape(chr(10).join(x)) + "</code></pre>")
    else:
        print("<pre><code>" + _html.escape(str(x)) + "</code></pre>")
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

The tag is upper-cased and validated, so a lower-case or stray entry is normalised or rejected, and never passed through untouched. A tag that contains anything other than letters and hyphens raises a `ValueError`, which catches a typo at the point of construction.

```python exec="1" source="material-block" session="designing-queries"
out(sf.wrap_field("graphene", "title-abs-key"))   # upper-cased to TITLE-ABS-KEY

try:
    sf.wrap_field("graphene", "TITLE_ABS")           # underscore is not allowed
except ValueError as exc:
    print(exc)
```

## One term, many disciplines

[`scopus_query`][scopusflow.query.scopus_query] builds on `wrap_field` and serves any field. Each call below returns the exact query string, with the `field` argument applied to every term.

```python exec="1" source="material-block" session="designing-queries"
out([
    # molecular biology
    sf.scopus_query("CRISPR", field="TITLE-ABS-KEY"),
    sf.scopus_query("gravitational waves", field="TITLE-ABS-KEY"),  # physics
    # environmental science
    sf.scopus_query("microplastics", field="TITLE-ABS-KEY"),
    # computer science
    sf.scopus_query("blockchain", field="TITLE-ABS-KEY"),
    sf.scopus_query("digital humanities", field="AUTHKEY"),         # humanities
])
```

The last example uses `AUTHKEY`, the author-supplied keywords, which isolates work that self-identifies with a field and so cuts incidental mentions.

## Combining terms with boolean operators

Passing several terms joins them into one query. The default operator is `AND`, and `OR` or `AND NOT` are available through the `op` argument. The same `field` is wrapped around each term before the terms are joined. Without a field, a term of several words is put in brackets, so each term stays one operand of the join (see [Phrases](#phrases) below).

```python exec="1" source="material-block" session="designing-queries"
# Two concepts that must co-occur (materials science).
out(sf.scopus_query("perovskite", "solar cell", field="TITLE-ABS-KEY"))

# Two names for one condition, either of which will do (medicine).
out(sf.scopus_query('"heart attack"', '"myocardial infarction"', op="OR"))

# A family of related tools (molecular biology).
out(sf.scopus_query("CRISPR", "Cas9", "Cas12", op="OR"))

# Exclude a neighbouring literature (medicine).
out(sf.scopus_query(
    "hypertension", "pulmonary", op="AND NOT", field="TITLE-ABS-KEY"
))
```

An operator outside the permitted set raises a `ValueError`, so `op="NOT"` or a typo is caught before the string is built, well short of a rejection from the API.

## Phrases

Scopus joins the words of an unquoted term with AND, so `heart attack` finds records that mention both words anywhere in the searched field. Double quotation marks ask for a loose phrase, whose words must sit next to each other, although punctuation is ignored and plurals are included. Braces ask for an exact phrase, including any stop words, spaces and punctuation. Elsevier's [search tips](https://dev.elsevier.com/sc_search_tips.html) describe all three.

```python exec="1" source="material-block" session="designing-queries"
out([
    sf.scopus_query('"heart attack"', field="TITLE-ABS-KEY"),  # loose phrase
    sf.scopus_query("{heart attack}", field="TITLE-ABS-KEY"),  # exact phrase
])
```

[`scopus_query`][scopusflow.query.scopus_query] leaves both kinds of phrase as written. When terms are joined without a field tag, a term of several unquoted words is put in brackets, so it stays one operand of the join. Joined bare, the first query below would read as `machine AND (learning OR deep) AND learning`.

```python exec="1" source="material-block" session="designing-queries"
out([
    sf.scopus_query("machine learning", "deep learning", op="OR"),
    sf.scopus_query('"machine learning"', '"deep learning"', op="OR"),
])
```

## Brackets in a query written by hand

A query that mixes operators needs brackets to say what it means. The search tips state that Scopus applies OR first, then AND, then AND NOT, so `A AND NOT B AND C` reads as `A AND NOT (B AND C)`. Elsevier has announced a new order, with AND NOT first, then AND, then OR ([Feldner, 2025](https://blog.scopus.com/boolean-searches-in-scopus-understanding-operator-precedence-best-practices/)), under which `A OR B AND C` reads as `A OR (B AND C)`. Brackets give the same reading under either order.

The package brackets the strings it composes. A query built by an earlier `scopus_query` call keeps its own join together when it is joined again, as below, and [`compare_topics`][scopusflow.compare.compare_topics] and [`scopus_intersections`][scopusflow.intersections.scopus_intersections] bracket each side of their joins. Plans, counts and trends append the year limit to the query, bracketing the query first wherever an operator would otherwise take the limit from part of it, as the last section shows.

```python exec="1" source="material-block" session="designing-queries"
young = sf.scopus_query("children", "adolescents", op="OR")
out(sf.scopus_query("vaccine", young))
```

## Searching by affiliation

Field tags reach beyond topics. `AFFILORG` searches the affiliation organisation name, which turns a query into an institution-level view of output.

```python exec="1" source="material-block" session="designing-queries"
out(sf.scopus_query("Max Planck", field="AFFILORG"))
```

## When a term is empty

The builder validates its input, so a stray empty term is caught at construction, well before it can produce a malformed query that fails downstream. An empty or whitespace-only term raises a `ValueError`.

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
# the expression every cell starts from
out(plan.wrapped_query)
out([(c.cell, c.year) for c in plan.cells()])      # one cell per year
```

Each cell sends that expression with its own year appended, so the first cell here asks for `TITLE-ABS-KEY(gut microbiome) AND PUBYEAR IS 2015`. An expression with a top-level OR, AND NOT or proximity operator is put in brackets before the year is added, so the limit applies to all of it. Any other expression is sent exactly as shown. The R twin sends the year as a separate request parameter, so its query strings never carry the limit.

Sizing and running the plan both contact the Scopus API, so the two calls below need a key configured for pybliometrics (in its standard `~/.config/pybliometrics.cfg`, or through `pybliometrics.init`) and are the only step here that goes online. [`scopus_count`][scopusflow.count.scopus_count] reports how many records the query matches without downloading them, which is the cheap way to check a search before committing quota to it.

```python
# Both calls require a configured Scopus API key.
sf.scopus_count(
    "gut microbiome", years=range(2015, 2023), field="TITLE-ABS-KEY"
)
records = sf.fetch_plan(plan)
```
