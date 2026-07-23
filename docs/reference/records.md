# Records

Normalise results into one stable schema, tally the most frequent values, and
export to reference-manager formats.

--8<-- "_snippets/plot-setup.md"

::: scopusflow.records.to_records

::: scopusflow.records.top

The tally below runs at build time over the bundled example harvest, so it needs
no key.

```python exec="1" source="material-block" session="reference-analyse"
records = sf.example_records()
out(sf.top(records, by="source", n=5))
```

::: scopusflow.records.RECORD_COLUMNS

::: scopusflow.data.example_records

::: scopusflow.export.to_bibtex

::: scopusflow.export.to_ris
