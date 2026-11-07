# Designing queries

[`scopus_query`][scopusflow.query.scopus_query] composes field-tagged Scopus queries from separate terms. A query pasted together by hand can contain a missing bracket or a mistyped tag and return the wrong records without an error. Everything here is string construction and runs offline without an API key. Each call returns the query as a literal string that you can read before you spend quota on it. A count, a trend or a harvest sends that string with any year limit appended, as [From a query to a plan](#from-a-query-to-a-plan) shows.

```python exec="1" session="designing-queries"
import html as _html
import pandas as pd
import scopusflow as sf


def _clean_table(html_table):
    # Drop pandas' own class and header alignment so the theme's table
    # styling (padding, borders, the navy header band) applies instead.
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

A field tag restricts a query to part of a record. The [`FIELD_TAGS`][scopusflow.query.FIELD_TAGS] dictionary maps the common tags to a short description of what each one searches. Because it is an ordinary dictionary, you can check membership before building a query, for example with `"AUTHKEY" in sf.FIELD_TAGS`.

```python exec="1" source="material-block" session="designing-queries"
out([f"{tag:<20} {meaning}" for tag, meaning in sf.FIELD_TAGS.items()])
```

The most generally useful tag is `TITLE-ABS-KEY`, which searches the title, abstract and keywords together. It is broad enough to find work on a topic without the incidental matches of a full-text search.

## Wrapping a single term

[`wrap_field`][scopusflow.query.wrap_field] applies one tag to one term, and the rest of the package uses it to add field tags. Passing `None` as the field returns the term unchanged. Use `None` for a term that already has its own tag.

```python exec="1" source="material-block" session="designing-queries"
out(sf.wrap_field("graphene", "TITLE-ABS-KEY"))
out(sf.wrap_field("graphene", None))
```

The tag is upper-cased and then checked. A tag that contains anything other than letters and hyphens raises a `ValueError`, so a typo is caught when the query is built.

```python exec="1" source="material-block" session="designing-queries"
out(sf.wrap_field("graphene", "title-abs-key"))   # upper-cased to TITLE-ABS-KEY

try:
    sf.wrap_field("graphene", "TITLE_ABS")           # underscore is not allowed
except ValueError as exc:
    print(exc)
```

## One term, many disciplines

[`scopus_query`][scopusflow.query.scopus_query] builds on `wrap_field` and works the same way in any discipline. Each call below returns the exact query string, with the `field` argument applied to every term.

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

The last example uses `AUTHKEY`, the author-supplied keywords. It finds work whose authors chose the term as a keyword and so returns fewer records that mention it only in passing.

## Combining terms with boolean operators

Passing several terms joins them into one query. The default operator is `AND`, and `OR` or `AND NOT` are available through the `op` argument. An operator outside these three, such as `op="NOT"` or a typo, raises a `ValueError` before the string is built. The same `field` is wrapped around each term before the terms are joined. Without a field tag, a term of several unquoted words is put in brackets, as [Phrases](#phrases) below explains.

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

## Phrases

Scopus joins the words of an unquoted term with AND, so `heart attack` finds records that mention both words anywhere in the searched field. Double quotation marks ask for a loose phrase, whose words must be adjacent, although punctuation is ignored and plurals are included. Braces ask for an exact phrase, including any stop words, spaces and punctuation. Elsevier's [search tips](https://dev.elsevier.com/sc_search_tips.html) describe all three.

```python exec="1" source="material-block" session="designing-queries"
out([
    sf.scopus_query('"heart attack"', field="TITLE-ABS-KEY"),  # loose phrase
    sf.scopus_query("{heart attack}", field="TITLE-ABS-KEY"),  # exact phrase
])
```

[`scopus_query`][scopusflow.query.scopus_query] leaves both kinds of phrase as written. When terms are joined without a field tag, a term of several unquoted words is put in brackets, so it stays one operand of the join. Without the brackets, the first query below would read as `machine AND (learning OR deep) AND learning`.

```python exec="1" source="material-block" session="designing-queries"
out([
    sf.scopus_query("machine learning", "deep learning", op="OR"),
    sf.scopus_query('"machine learning"', '"deep learning"', op="OR"),
])
```

## Brackets in a query written by hand

A query that mixes operators needs brackets to make its grouping unambiguous. The search tips state that Scopus applies OR first, then AND, then AND NOT, so `A AND NOT B AND C` reads as `A AND NOT (B AND C)`. Elsevier has announced a new order, with AND NOT first, then AND, then OR ([Feldner, 2025](https://blog.scopus.com/boolean-searches-in-scopus-understanding-operator-precedence-best-practices/)), under which `A OR B AND C` reads as `A OR (B AND C)`. Brackets give the same reading under either order.

The package brackets the strings it composes. [`compare_topics`][scopusflow.compare.compare_topics] and [`scopus_intersections`][scopusflow.intersections.scopus_intersections] bracket each side of their joins. Plans, counts and trends append the year limit to the query. Where an operator would otherwise leave part of the query outside the limit, they bracket the query first, as [From a query to a plan](#from-a-query-to-a-plan) shows. A query built by an earlier `scopus_query` call stays one operand when it is joined again, as in the example below.

```python exec="1" source="material-block" session="designing-queries"
young = sf.scopus_query("children", "adolescents", op="OR")
out(sf.scopus_query("vaccine", young))
```

## Searching by affiliation

Field tags can also search parts of a record that do not describe its topic. `AFFILORG` searches the affiliation organisation name, so a query can retrieve the output of an institution.

```python exec="1" source="material-block" session="designing-queries"
out(sf.scopus_query("Max Planck", field="AFFILORG"))
```

## When a term is empty

[`scopus_query`][scopusflow.query.scopus_query] checks its terms as it builds the query. An empty or whitespace-only term raises a `ValueError` before a malformed query can be produced.

```python exec="1" source="material-block" session="designing-queries"
try:
    sf.scopus_query("graphene", "")
except ValueError as exc:
    print(exc)
```

## Checks before any request

[`SearchPlan`][scopusflow.plan.SearchPlan], [`scopus_count`][scopusflow.count.scopus_count], [`scopus_trend`][scopusflow.trend.scopus_trend], [`compare_topics`][scopusflow.compare.compare_topics] and [`scopus_intersections`][scopusflow.intersections.scopus_intersections] check each query offline before anything is sent and raise a `ValueError` for three mistakes. Refinement syntax copied from the web interface, such as `LIMIT-TO(DOCTYPE, "ar")`, is ignored by the Search API, so the search would run unfiltered with no sign of a problem. A field tag wrapped around a query that already opens with one is rejected by the API, and `wrap_field` raises the same error. A bracket, quotation mark or brace left unclosed changes what the rest of the query means. The message of each error says what to write instead. The messages are those of the R twin, word for word.

```python exec="1" source="material-block" session="designing-queries"
import textwrap

try:
    sf.SearchPlan('working memory AND (LIMIT-TO (DOCTYPE, "ar"))')
except ValueError as exc:
    print(textwrap.fill(str(exc), 76))
```

Written as search fields, the same limits pass the check.

```python exec="1" source="material-block" session="designing-queries"
out(sf.SearchPlan("working memory AND DOCTYPE(ar) AND LANGUAGE(english)").wrapped_query)
```

A strategy pasted from the advanced search with its own tags, such as `TITLE-ABS-KEY ( "working memory" )`, is sent as written when `field` is left as `None`. `INDEXTERMS()`, which pybliometrics documents as not working through the Search API, issues a `scopusflow.query.QuerySyntaxWarning`. `KEY()` searches the index terms together with author keywords, trade names and chemical names.

## From a query to a plan

A composed query can be passed directly to the rest of the workflow. A [`SearchPlan`][scopusflow.plan.SearchPlan] takes it as its query, and a year-partitioned plan fetches and checkpoints it one year at a time. The plan can apply the field tag itself through its own `field` argument, so you pass the bare topic and let the plan wrap it once.

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

Each cell sends that expression with its own year appended. For the first cell here, the query is `TITLE-ABS-KEY(gut microbiome) AND PUBYEAR IS 2015`. An expression with a top-level OR, AND NOT or proximity operator is put in brackets before the year is added, so the limit applies to all of it. Any other expression is sent exactly as shown. The R twin sends the year as a separate request parameter and never adds it to the query string.

Sizing and running the plan contact the Scopus API, so the two calls below need your key. No other step here contacts the API. pybliometrics keeps the key in its configuration file, `~/.config/pybliometrics.cfg`, and reads it only when `pybliometrics.init()` is called. The call is needed once in every session. [`scopus_count`][scopusflow.count.scopus_count] reports how many records the query matches without downloading them and is the cheap way to check a search before committing quota to it.

```python
import pybliometrics

pybliometrics.init()   # once per session, before the first search

sf.scopus_count(
    "gut microbiome", years=range(2015, 2023), field="TITLE-ABS-KEY"
)
records = sf.fetch_plan(plan)
```

## Checking recall against known records

A search strategy can be tested against records that are already known to be relevant and were collected independently of it, for instance the studies included in an earlier review or those named by experts. The share of them the strategy retrieves is its relative recall ([Sampson et al., 2006](https://doi.org/10.1186/1471-2288-6-33)), and [Bramer et al. (2018)](https://doi.org/10.5195/jmla.2018.283) make the check a step in developing a search.

The check runs two searches for each chain of DOIs joined by OR, both under the same year limit. The chain alone finds which known records Scopus indexes, and the strategy joined to the chain finds which of those it retrieves. A known record the chain does not find, because Scopus does not index it or holds it without that DOI, cannot show whether the strategy finds it. It is left out of the denominator and listed, so it can be checked by hand.

The sketch below contacts the API, so it is not run here. Its DOIs are placeholders for your own, and [`extract_dois`][scopusflow.diff.extract_dois] cleans them first, so a resolver prefix or a difference in case does no harm. Chains of at most 25 DOIs keep each request short. How the API treats much longer chains has not been checked.

```python
known = sf.extract_dois(
    ["10.xxxx/known-1", "https://doi.org/10.xxxx/known-2", "doi:10.xxxx/known-3"]
)
strategy = sf.scopus_query("working memory", "training", field="TITLE-ABS-KEY")
years = range(2010, 2025)

chains = [
    " OR ".join(f'DOI("{doi}")' for doi in known[i:i + 25])
    for i in range(0, len(known), 25)
]


def found(query):
    records = sf.fetch_plan(sf.SearchPlan(query, years=years))
    return {doi.lower() for doi in sf.extract_dois(records)}


indexed = set().union(*(found(chain) for chain in chains))
retrieved = set().union(*(found(f"({strategy}) AND ({chain})") for chain in chains))
not_found = sorted({doi.lower() for doi in known} - indexed)
relative_recall = len(retrieved) / len(indexed)
```

The relative recall describes the strategy against this reference set alone, so report the set, its source and the DOIs left out alongside it.
