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


# The bundled worked-example harvest, over the RECORD_COLUMNS schema, so the
# examples below run at build time without a key and without contacting the API.
records = sf.example_records()
```
