# Running the pipeline in BigQuery

The same SQL files that run in DuckDB run in Google BigQuery, and the run ends
by checking that both engines produced the same numbers. This is the third
engine for the canonical SQL, after DuckDB (tested) and SQL Server (written, untested).

Only the public dataset and the synthetic export go to BigQuery. The runner
refuses any other source. See "Data handling" in the [README](../README.md).

## Setup (once, about 10 minutes)

1. **Create a project.** Open
   [console.cloud.google.com/bigquery](https://console.cloud.google.com/bigquery),
   sign in, and create a project when asked. Note the project id.
2. **Install the gcloud CLI** by following
   [cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install).
3. **Sign in.** The first command is for gcloud itself, the second stores
   credentials that the Python client finds on its own, so no key file is created:

   ```
   gcloud auth login
   gcloud auth application-default login
   gcloud config set project YOUR_PROJECT
   gcloud auth application-default set-quota-project YOUR_PROJECT
   ```

**Sandbox or billing.** A project without billing runs in the free sandbox
(10 GiB storage, 1 TiB of queries a month, no card), and the pipeline runs
there unchanged. The sandbox deletes every table after 60 days and, worse for
historical data, empties date-partitioned tables (see below). With billing
linked, the same free monthly allowances apply and this project costs about $0.
This project uses billing, with three guards:

- **Budget alert:** $5 CAD a month on the project, emailing at 50%, 90%, 100%
  and at a forecast of 100%. Created with `gcloud billing budgets create`. A
  budget only alerts; it does not stop spending.
- **Daily query quota:** the hard stop. In the Console, IAM & Admin → Quotas,
  filter for BigQuery API "Query usage per day", and set a limit. BigQuery
  refuses queries beyond it.
- **Per-query cap:** every job the scripts send carries `maximum_bytes_billed`.

After linking billing, clear the sandbox's 60-day defaults on each dataset
(`default_table_expiration_ms`, `default_partition_expiration_ms`) and on each
existing table (`expires`). Otherwise tables created in the sandbox still expire.

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

Tested on 2026-11-14 on both sources, first in the sandbox and again after billing was linked. All
FATAL QA checks pass, and all 215 aggregates in `engine_comparison.csv` match
the DuckDB run on each source. A full run billed 449 MB (public dataset, 20
jobs) and 273 MB (synthetic, 17 jobs), most of it BigQuery's minimum charge
of 10 MB per table read. The DDL-only change left the DuckDB outputs as they
were: all 14 output CSVs match row for row on both sources.

## Partitioning and clustering, measured

`scripts/bigquery_layout_benchmark.py` copies `fact_stay_night` (409,257 rows,
69 MB) into four layouts and runs the same six queries on each, with the
query cache off. Full results are in `out/bigquery/antonio/layout_benchmark.csv`.

```
uv run scripts/bigquery_layout_benchmark.py --project YOUR_PROJECT
```

The layouts: plain; `PARTITION BY DATE_TRUNC(stay_date, MONTH)`;
`CLUSTER BY stay_date, property_code, business_source`; and monthly partitions
with `CLUSTER BY property_code, business_source`.

MB processed, and MB billed in brackets (BigQuery bills at least 10 MB per table read):

| Query | Plain | Monthly partitions | Clustered on date | Partitioned + clustered |
|---|---|---|---|---|
| q1: one stay month at one hotel | 15.6 (15.7) | **0.7** (10.5) | 15.6 (15.7) | **0.7** (10.5) |
| q1b: room-nights booked in one month (filters `booking_date`) | 12.6 (13.6) | 12.6 (13.6) | 12.6 (13.6) | **7.1** (10.5)\* |
| q2: one stay night at one hotel | 23.7 (24.1) | **0.7** (10.5) | 23.7 (24.1) | **0.7** (10.5) |
| q3: one source of business, all dates | 9.5 (10.5) | 9.5 (10.5) | 9.5 (10.5) | 9.5 (10.5) |
| q4: room-nights by property, no filter | 6.1 (10.5) | 6.1 (10.5) | 6.1 (10.5) | 6.1 (10.5) |
| q5: `SELECT * … LIMIT 10` | 69.1 | 69.1 | 69.1 | 69.1 |

\* The dry run estimated 12.6 MB; 7.1 MB was read.

What this shows:

- **Partition pruning works when the filter is on the partition column.** One
  stay month (q1) or one stay night (q2) reads about 95–97% less.
- **A filter on another date column gets no partition pruning.** q1b asks a
  pickup question by `booking_date`, and the partitioned-only table reads as much
  as the plain one.
- **At this size, the 10 MB minimum hides most of the saving.** q2 goes from
  24.1 MB to 10.5 MB billed, not to 0.7 MB.
- **Clustering alone does nothing at 69 MB.** Google's guidance is that clustering
  pays off above about 64 MB per table or partition, and that partitions should
  hold about 10 GB or more. This table is at the edge of the first and far below
  the second.
- **A dry run cannot see clustering savings.** In q1b, the partitioned and
  clustered table was estimated at 12.6 MB and read 7.1 MB. The likely reason
  is that BigQuery keeps min/max values per storage block and skips blocks that
  cannot match. Bookings made in August 2016 are never for stays before August
  2016, so whole months of blocks are skipped. Partition pruning shows up in the
  estimate; block pruning only shows up after the query runs.
- **`LIMIT` does not reduce bytes scanned.** `SELECT *` reads every column of every
  row whatever the layout, which made q5 the most expensive query in the test.
  Naming only the columns you need (q4 reads 6 MB) matters more here than any layout.

**Decision: the canonical table stays unpartitioned.** At 69 MB, the saving is
at most 14 MB billed per query (q2), and Google advises against partitions this
small (about 2.5 MB a month here). The layout to use once the table reaches
gigabytes per month (many properties, several years of history) is partitioned
by stay month and clustered by property and source of business.

**Sandbox gotcha: date partitions on historical data disappear.** The sandbox
forces a 60-day partition expiration, counted from each partition's own date, and
`OPTIONS (partition_expiration_days = NULL)` does not override it. In the sandbox,
a table partitioned by `DATE_TRUNC(stay_date, MONTH)` was created with 0 rows,
because every stay date is from 2015–2017. Integer-range partitioning on a
`stay_year_month` key (`201608`) avoids the expiration, but then queries must filter
on that key to be pruned. Linking billing and clearing the dataset defaults fixed
it, and the benchmark now uses date partitions.

**Changing partitioning needs a DROP.** `CREATE OR REPLACE TABLE` cannot change
an existing table's partitioning, so the benchmark drops and recreates each table.

## Next

- Pickup forecasting with BigQuery ML (`ARIMA_PLUS`), roadmap item 4.
- A Looker Studio dashboard on the booking-curve marts.
