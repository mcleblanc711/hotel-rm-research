# Hotel RM Research

Hotel revenue-management analysis built on the public Hotel Booking Demand
dataset (Antonio, Almeida & Nunes, 2019), designed so the same SQL and Excel
tooling can be pointed at a private PMS export without changes.

Work in progress. See `docs/` for the schema and `sql/` for the pipeline.

## Run

```
uv run --with duckdb scripts/run_pipeline.py --source antonio
```

Outputs land in `out/antonio/` (canonical CSVs, QA report, manifest).
