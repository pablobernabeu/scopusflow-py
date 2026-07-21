# Records

Normalise results into one stable schema, tally the most frequent values, and
export to reference-manager formats.

--8<-- "_snippets/plot-setup.md"

::: scopusflow.records.to_records

::: scopusflow.records.top

The tally below runs at build time over a small synthetic frame of the
`RECORD_COLUMNS` shape, so it needs no key.

```python exec="1" source="material-block" session="reference-analyse"
out(sf.top(records, by="source"))
```

::: scopusflow.records.RECORD_COLUMNS

::: scopusflow.export.to_bibtex

::: scopusflow.export.to_ris
