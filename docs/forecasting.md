# Pickup forecasting backtest

On 28 February 2017, forecast the final room-nights of every night from
1 March to 31 August 2017 at both hotels, using only what was on the books that
day. Then compare with what actually stayed. Five models, one forecast date,
184 nights × 2 hotels.

```
uv run --with duckdb scripts/run_pipeline.py --source antonio          # models 1-3, portable SQL
uv run scripts/run_bigquery.py --source antonio --project YOUR_PROJECT # same in BigQuery, checked against DuckDB
uv run scripts/bigquery_forecast_dashboard.py --project YOUR_PROJECT   # models 4-5 + dashboard tables
```

## The models

| # | Model | Where | How it forecasts a night `d` days out |
|---|---|---|---|
| 1 | On the books only | portable SQL | What is booked now. A floor, not a forecast |
| 2 | Additive pickup | portable SQL | On the books + the average room-nights added from `d` days out to the night, by property and day of week |
| 3 | Multiplicative pickup | portable SQL | On the books × (sum of finals / sum on the books at `d` days out), by property and day of week |
| 4 | BigQuery ML linear regression | `sql/bigquery_ml/linear_pickup.sql` | Learns a weight on on-the-books per horizon, plus intercepts by property × horizon, day of week and month, plus last-7-day pickup |
| 5 | BigQuery ML ARIMA_PLUS | `sql/bigquery_ml/arima_plus.sql` | Time series of nightly finals per hotel, with Portuguese holidays. Never sees what is on the books |

Models 1–3 are in `sql/forecast/`, written in the same portable SQL as the rest of
the pipeline. They run in DuckDB, and in BigQuery with results checked to match.
They are the ones to take to a SQL Server PMS database.

Training uses stay nights from 1 August 2015 to 28 February 2017 (July 2015
is skipped because its early nights miss guests who arrived before the data
starts). For those nights the pickup curves are built at every days-out value
from 1 to 184. Nothing after the forecast date is used.

## Results

WAPE (sum of |forecast − actual| ÷ sum of actual), both hotels. Lower is better.

| Model | 1–7 days | 8–14 | 15–30 | 31–60 | 61–90 | 91–184 | All |
|---|---|---|---|---|---|---|---|
| 1 On the books only | 7.1% | 9.9% | 9.9% | 15.9% | 20.7% | 29.4% | 22.7% |
| 2 Additive pickup | **2.5%** | **2.7%** | **7.7%** | 13.0% | 15.2% | 21.6% | 16.6% |
| 3 Multiplicative pickup | 2.7% | 4.1% | 13.1% | 24.3% | 38.2% | 94.1% | 60.4% |
| 4 BigQuery ML linear regression | 9.4% | 7.9% | 9.6% | **7.2%** | **6.4%** | **9.1%** | **8.4%** |
| 5 BigQuery ML ARIMA_PLUS | 12.3% | 10.4% | 11.9% | 10.3% | 12.9% | 13.0% | 12.4% |
| Nights in bucket | 14 | 14 | 32 | 60 | 60 | 188 | 368 |

What it shows:

- **Inside a month, additive pickup wins.** What is on the books carries most of
  the information, and adding a typical pickup to it is hard to beat.
- **Beyond a month, the linear model wins.** Its weights on what is on the
  books fall from 0.71 at a week out to 0.45 at 3–6 months: it trusts early
  bookings less and leans on day-of-week and month averages. A horizon-blended
  forecast (pickup up to about 30 days out, the regression beyond) would beat
  every single model here. That is how many RM systems work.
- **Multiplicative pickup falls apart at long horizons.** A ratio fitted on small
  early counts magnifies any change in how far ahead guests book, so it
  over-forecasts by 93% at 3–6 months out.
- **ARIMA_PLUS is steady but never sharp.** Knowing nothing about bookings, it
  is about as good at a week out as at six months. It found weekly seasonality
  and holiday effects, but not yearly seasonality: 19 months of history is not
  enough for it to detect a yearly cycle.
- **Its 80% intervals are too wide.** They contained the actual 95.7% of the
  time, so it is under-confident.

## Caveats

- **The hotels sell out.** Final counts plateau (city hotel: average 216
  room-nights a night, maximum 230; resort: 174 and 186). Demand above capacity
  is invisible. That compresses finals near capacity and flatters models that
  predict "about normal" (4 and 5) at long horizons. Room counts are not
  published, so no model is capped and nothing is unconstrained here.
- **One forecast date.** The 1–14 day buckets hold 14 nights each. A rolling
  backtest (a forecast every week, scored at fixed days out) would give firmer
  numbers. It is the next step for this module.
- **Reconstructed pace.** On-the-books counts come from each booking's final
  state and a derived booking date (see the README). Modifications are invisible.
- **No-shows count as on the books**, as in the booking-curve mart.
