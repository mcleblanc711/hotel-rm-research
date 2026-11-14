# Public Looker Studio dashboard

A three-page Looker Studio report on the `hotel_rm_public` BigQuery dataset:
booking pace, forecast vs actual, and forecast accuracy. Looker Studio has no
API for building reports, so the layout is done by hand from the spec below
(about 45 minutes). The tables it reads are built by
`scripts/bigquery_forecast_dashboard.py`.

## What viewers can reach, and what it costs

- **Only `hotel_rm_public`.** It holds three small, pre-aggregated tables built
  from the public dataset: `forecast_nightly` (1,840 rows), `forecast_accuracy`
  (105 rows) and `booking_pace` (115,290 rows, 8 MB). A Looker Studio data source
  queries with its owner's credentials, so viewers see these tables through the
  report's charts and nothing else in the project.
- **Each chart a viewer loads is a BigQuery query billed to this project**, at
  BigQuery's 10 MB minimum. Looker Studio caches results (12 hours by default),
  and the free tier covers 1 TiB of queries a month, about 100,000 uncached chart
  loads. The project's daily query quota is the hard stop if a link spreads.
- **To remove BigQuery from the viewing path entirely,** switch each data source
  to an extract (Add data → Extract Data, pick the fields, set auto-update to
  weekly). Viewers then read Looker Studio's stored copy.

## Create the report

`scripts/bigquery_forecast_dashboard.py` prints a Looker Studio link at the end.
Opening it creates a new report with the three tables already connected as data
sources. If it opens a blank report instead, add each table by hand:
Add data → BigQuery → project `hotelrmresearch` → dataset `hotel_rm_public`.

For each data source (Resource → Manage added data sources → Edit):
- Data credentials: **Owner's credentials**.
- Data freshness: 12 hours.
- Add the calculated fields listed for its page below.

## Page 1: Booking pace

Data source `booking_pace`. Calculated fields:

| Field | Formula |
|---|---|
| On the books % of final | `SUM(on_books_rn) / SUM(final_rn)` |
| Gross booked % of final | `SUM(gross_booked_rn) / SUM(final_rn)` |
| Cancellation share | `SUM(canceled_rn) / SUM(gross_booked_rn)` |

- **Controls** across the top: drop-down on `property`, drop-down on `business_source`,
  date range control on `stay_month`.
- **Line chart:** dimension `days_out`, metrics *On the books % of final* and
  *Gross booked % of final*. Sort by `days_out` descending so time runs left to
  right toward the stay night. Format both as percent.
  Title: "How far ahead the nights fill".
- **Second line chart:** same, metric *On the books % of final* only, breakdown
  dimension `business_source`. Title: "Groups book early, then wash; corporate books late".
- **Scorecard:** *Cancellation share*, with a chart filter `days_out = 0`.
  Title: "Share of booked room-nights that cancel".

## Page 2: Forecast vs actual

Data source `forecast_nightly`.

- **Controls:** drop-down on `property`, drop-down on `model` (single select,
  default "2 Additive pickup").
- **Time series:** dimension `stay_date`, metrics `actual_rn`, `forecast_rn`,
  `otb_rn` (all SUM). Rename them Actual, Forecast and On the books on 28 Feb.
  Title: "Forecast made 28 Feb 2017 vs what stayed".
- **Table:** `stay_date`, `stay_dow`, `property`, `days_out`, `otb_rn`,
  `forecast_rn`, `actual_rn`, `error_rn`. Conditional formatting on `error_rn`
  (red above +10, blue below −10).
- Optional: with `model` = "5 BigQuery ML ARIMA_PLUS", add `lower_rn` and
  `upper_rn` to the time series to show the 80% interval.

## Page 3: Accuracy

Data source `forecast_accuracy`.

- **Control:** drop-down on `property`, default "Both hotels".
- **Pivot table with heatmap:** row dimension `model`, column dimension
  `horizon` (sorted by `horizon_bucket`), metric `wape` (AVG; one row per cell)
  formatted as percent. Exclude "All horizons" with a filter, then add a separate
  small table for the all-horizons column.
- **Bar chart:** dimension `horizon` (sorted by `horizon_bucket`), breakdown
  `model`, metric `wape`. Title: "Error by days out: pickup wins near in, the
  regression wins far out".
- **Text box** with the method in three lines and the main caveats (one forecast
  date; the hotels sell out, so finals sit near capacity; pace is reconstructed),
  linking to `docs/forecasting.md` in the GitHub repo.

## Every page

- A footer text box: "Data: Hotel Booking Demand (Antonio, Almeida & Nunes, 2019),
  CC BY 4.0. Two Portuguese hotels, 2015–2017. Built with BigQuery and BigQuery ML."
  plus the GitHub link.
- Theme: one accent colour for "Actual" and a muted one for forecasts, used the
  same way on every page.

## Publish

1. Share → Manage access, and change link access from restricted to **public**
   (anyone on the internet can find and view it) or **unlisted** (anyone with the
   link, but not searchable). The exact labels vary between Looker Studio versions.
2. In the same dialog, decide whether viewers may download, print and copy the
   data. The data is public either way, so this is a matter of taste.
3. Copy the link into the README, and add a screenshot to `docs/img/`.
