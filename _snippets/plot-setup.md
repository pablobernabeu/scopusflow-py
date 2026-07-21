```python exec="1" session="reference-analyse"
import html as _html
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import scopusflow as sf
from io import StringIO


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
    else:
        print("<pre><code>" + _html.escape(str(x)) + "</code></pre>")


def show():
    plt.gcf().set_size_inches(7.2, 3.8)
    plt.tight_layout()
    plt.gcf().canvas.draw()  # let the label de-collision settle before saving
    buffer = StringIO()
    # Transparent so the page background shows through in both colour schemes;
    # matplotlib otherwise paints an opaque white figure and axes patch.
    plt.savefig(buffer, format="svg", transparent=True)
    plt.close()
    print(buffer.getvalue())


# A small synthetic record set over the RECORD_COLUMNS schema, so the examples
# below run at build time without a key and without contacting the API.
_sources = ["Nature", "Science", "Carbon", "Nano Letters", "Advanced Materials"]
_authors = ["Lee J.", "Park S.", "Kim H.", "Garcia M.", "Zhang F.", "Abbott B."]
_sizes = [6, 9, 8, 14, 22, 31, 47]
_rows = []
for _yi, _year in enumerate(range(2016, 2023)):
    for _j in range(_sizes[_yi]):
        _rows.append({
            "entry_number": len(_rows) + 1,
            "scopus_id": f"{_year}{_j:03d}",
            "doi": f"10.1000/demo.{_year}.{_j:03d}",
            "title": f"Record {_j + 1} from {_year}",
            "authors": _authors[_j % len(_authors)],
            "year": _year, "date": f"{_year}-01-01",
            "publication": _sources[(_j * 3 + _yi) % len(_sources)],
            "citations": (_j * 7 + _year) % 120,
            "query": "graphene supercapacitor",
        })
records = pd.DataFrame(_rows, columns=sf.RECORD_COLUMNS)
```
