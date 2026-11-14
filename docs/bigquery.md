# Running the pipeline in BigQuery

The same SQL files that run in DuckDB run in Google BigQuery, and the run ends
by checking that both engines produced the same numbers. This is the third
engine for the canonical SQL, after DuckDB (tested) and SQL Server (written, untested).

Only the public dataset and the synthetic export go to BigQuery. The runner
refuses any other source. See "Data handling" in the [README](../README.md).

## Setup (once, about 10 minutes, no card needed)

1. **Create a project in the BigQuery sandbox.** Open
   [console.cloud.google.com/bigquery](https://console.cloud.google.com/bigquery),
   sign in, and create a project when asked. A project without billing runs in
   the sandbox: 10 GiB of storage and 1 TiB of queries a month for free.
   Note the project id (for example `hotel-rm-123456`).
2. **Install the gcloud CLI** by following
   [cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install).
3. **Sign in for local tools.** This stores credentials the Python client finds
   on its own, so no key file is created:

   ```
   gcloud auth application-default login
   ```

## Run

```
uv run --with duckdb scripts/run_pipeline.py --source antonio            # DuckDB reference run
uv run scripts/run_bigquery.py --source antonio --project YOUR_PROJECT   # BigQuery run + comparison
uv run scripts/run_bigquery.py --source antonio --translate-only         # just write the SQL; no account needed
```

Each source gets its own dataset (`hotel_rm_antonio`, `hotel_rm_synthetic`).
Re-running replaces every table. Output goes to `out/bigquery/<source>/`:

| File | What it holds |
|---|---|
| `sql/*.sql` | The exact GoogleSQL sent to BigQuery, one file per job |
| `qa_report.csv` | QA results as BigQuery computed them |
| `engine_comparison.csv` | For every output table and column: row count, non-null count, and sum or distinct count, DuckDB vs BigQuery |
| `run_log.json` | Job id, bytes processed and bytes billed for each step |

The run fails if any FATAL QA check fails or any aggregate differs between engines.

## Design decisions

**The SQL is written once, in DuckDB's dialect, and translated.** The runner
uses [sqlglot](https://github.com/tobymao/sqlglot) to turn each file into
GoogleSQL. Translation covers type names (`VARCHAR` becomes `STRING`, `DOUBLE`
becomes `FLOAT64`), `a % b` (BigQuery has only `MOD(a, b)`) and identifier quoting.
The alternative, a hand-maintained second copy of every file, would drift.

**One translation bug, caught by reading the output.** sqlglot turns
`CAST(x AS DECIMAL(12, 2))` into `CAST(x AS NUMERIC)`. That is correct as far
as it goes, because BigQuery allows `NUMERIC(p, s)` only on table columns and
script variables. But it silently drops the rounding to 2 or 4 decimals, so
nightly revenue would no longer match DuckDB's. The runner rewrites these casts
to `ROUND(CAST(x AS NUMERIC), s)`. Both engines round halves away from zero, so
the results are the same. The sqlglot version is pinned because the translation
depends on it.

**The pipeline is DDL-only.** The free sandbox does not run DML (`INSERT`,
`UPDATE`, `DELETE`). Each QA file therefore creates its own `qa_*` table, and
the runner unions them into `qa_report`. The as-of date is set by recreating
`run_context` instead of updating it. Every step is a `CREATE OR REPLACE TABLE
… AS SELECT`, so a re-run gives the same result, on DuckDB as well.

**One job per SQL file, with the date helpers sent each time.** `add_days` and
`days_between` are `TEMP` functions in `sql/dialect/bigquery.sql`. A temp function
only lasts for the job that creates it, so the runner puts them at the top of
every job. Persistent functions in the dataset would also work. Temp functions
keep the dataset holding nothing but tables.

**Row numbers are added before upload.** BigQuery tables have no row order, but
the public dataset's surrogate `booking_id` is built from file position. The
runner numbers the rows while reading the CSV, so the IDs match DuckDB's.

**Data is uploaded as JSON.** Rows go up as newline-delimited JSON with explicit
nulls, every column as `STRING`, the same as DuckDB's `all_varchar` read. Typing
happens in the adapter SQL on both engines, not in the loader.

**There is a cost cap.** Every query job carries `maximum_bytes_billed` of 1 GiB,
so a bad query fails instead of scanning more. A full run should bill well under
1 GB, most of it BigQuery's minimum charge of 10 MB per table a query reads.
`run_log.json` records the actual figure.

## Status

Tested on 2026-11-14 in a BigQuery sandbox project, on both sources. All
FATAL QA checks pass, and all 215 aggregates in `engine_comparison.csv` match
the DuckDB run on each source. A full run billed 449 MB (public dataset, 20
jobs) and 273 MB (synthetic, 17 jobs), most of it BigQuery's minimum charge
of 10 MB per table read. The DDL-only change left the DuckDB outputs as they
were: all 14 output CSVs match row for row on both sources.

## Partitioning and clustering, measured

`scripts/bigquery_layout_benchmark.py` copies `fact_stay_night` (409,257 rows,
72 MB) into four layouts and runs the same five queries on each, with the
query cache off. Full results are in `out/bigquery/antonio/layout_benchmark.csv`.

```
uv run scripts/bigquery_layout_benchmark.py --project YOUR_PROJECT
```

MB processed, and MB billed in brackets (BigQuery bills at least 10 MB per table read):

| Query | Plain | Monthly partitions | Clustered on date | Partitioned + clustered |
|---|---|---|---|---|
| q1: one month at one hotel (filters on the month key) | 18.8 (18.9) | **0.9** (10.5) | 18.8 (18.9) | **0.9** (10.5) |
| q1b: same, but filters on `stay_date` only | 15.6 (15.7) | 15.6 (15.7) | 15.6 (15.7) | **0.7** (10.5)\* |
| q2: one stay night at one hotel | 27.0 (27.3) | **0.8** (10.5) | 27.0 (27.3) | **0.8** (10.5) |
| q3: one source of business, all dates | 9.5 (10.5) | 9.5 (10.5) | 9.5 (10.5) | 9.5 (10.5) |
| q4: room-nights by property, no filter | 6.1 (10.5) | 6.1 (10.5) | 6.1 (10.5) | 6.1 (10.5) |
| q5: `SELECT * … LIMIT 10` | 72.4 | 72.4 | 72.4 | 72.4 |

\* The dry run estimated 15.6 MB here; only 0.7 MB was read.

What this shows:

- **Partition pruning works, but only when the filter is on the partition
  column.** q1 reads 95% less with monthly partitions. q1b asks the same question
  through `stay_date` and gets no pruning from the partitioned-only table.
- **At this size, the 10 MB minimum hides most of the saving.** q1 goes from
  18.9 MB to 10.5 MB billed, not to 0.9 MB.
- **Clustering alone does nothing at 72 MB.** Google's guidance is that clustering
  pays off above about 64 MB per table or partition, and that partitions should
  hold about 10 GB or more. This table is under both.
- **A dry run cannot see clustering savings.** In q1b, the partitioned and
  clustered table was estimated at 15.6 MB and read 0.7 MB. The likely reason is
  that each month is stored in its own blocks, so BigQuery skips blocks whose
  date range cannot match. Partition pruning shows up in the estimate; block
  pruning only shows up after the query runs.
- **`LIMIT` does not reduce bytes scanned.** `SELECT *` reads every column of every
  row whatever the layout, which made q5 the most expensive query in the test.
  Naming only the columns you need (q4 reads 6 MB) matters more here than any layout.

**Decision: the canonical table stays unpartitioned.** At 72 MB, the saving is
at most 17 MB billed per query (q2), and getting it would mean adding a `stay_year_month` column
to the canonical schema for one engine. The layout to use once a table reaches
the gigabytes (many properties, several years of history) is
partitioned by stay month and clustered by property and source of business.

**Sandbox gotcha: date partitions on historical data disappear.** The sandbox
forces a 60-day partition expiration, counted from each partition's own date, and
`OPTIONS (partition_expiration_days = NULL)` does not override it. A table
partitioned by `DATE_TRUNC(stay_date, MONTH)` was created with 0 rows, because
every stay date is from 2015–2017. The benchmark uses integer-range partitions
on a `stay_year_month` key (`201608`), which have no expiration. A
billing-enabled project can use date partitions normally.

**Changing partitioning needs a DROP.** `CREATE OR REPLACE TABLE` cannot change
an existing table's partitioning, so the benchmark drops and recreates each table.

## Next

- Pickup forecasting with BigQuery ML (`ARIMA_PLUS`), roadmap item 4.
- A Looker Studio dashboard on the booking-curve marts.
