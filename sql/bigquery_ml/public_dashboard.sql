-- Tables for the public Looker Studio dashboard, in their own dataset.
-- GoogleSQL, BigQuery only. Run by scripts/bigquery_forecast_dashboard.py with the
-- source dataset as default; {{public_dataset}} is replaced by the runner.
--
-- Everything the public report can read is in {{public_dataset}}, and only
-- these three small, pre-aggregated tables are in it. A Looker Studio data source
-- runs queries with its owner's credentials, so the dataset is the boundary of
-- what viewers can see, and small tables keep viewer queries at the 10 MB minimum.
--   forecast_nightly   one row per test night x model: forecast, interval, actual
--   forecast_accuracy  WAPE / MAE / bias by model x property x horizon (+ 'ALL')
--   booking_pace       on-the-books share of final by days out, source, stay month

CREATE OR REPLACE TABLE {{public_dataset}}.forecast_nightly
OPTIONS (description = 'Backtest: forecasts made on forecast_date for each of the following nights, vs what actually stayed. Public Hotel Booking Demand dataset (Antonio et al., 2019).')
AS
SELECT
    c.forecast_date,
    f.property_code,
    CASE f.property_code WHEN 'CITY' THEN 'City hotel' WHEN 'RESORT' THEN 'Resort hotel'
         ELSE f.property_code END                                       AS property,
    f.stay_date,
    FORMAT_DATE('%a', f.stay_date)                                      AS stay_dow,
    f.days_out,
    f.horizon_bucket,
    f.model                                                             AS model_code,
    CASE f.model
        WHEN 'OTB_ONLY' THEN '1 On the books only'
        WHEN 'ADDITIVE_PICKUP' THEN '2 Additive pickup'
        WHEN 'MULTIPLICATIVE_PICKUP' THEN '3 Multiplicative pickup'
        WHEN 'BQML_LINEAR_REG' THEN '4 BigQuery ML linear regression'
        WHEN 'BQML_ARIMA_PLUS' THEN '5 BigQuery ML ARIMA_PLUS'
        ELSE f.model END                                                AS model,
    ROUND(f.forecast_rn, 1)                                             AS forecast_rn,
    ROUND(f.lower_rn, 1)                                                AS lower_rn,
    ROUND(f.upper_rn, 1)                                                AS upper_rn,
    f.actual_rn,
    f.otb_rn,
    ROUND(f.forecast_rn - f.actual_rn, 1)                               AS error_rn,
    ROUND(ABS(f.forecast_rn - f.actual_rn), 1)                          AS abs_error_rn
FROM fc_forecast f
CROSS JOIN fc_context c;

CREATE OR REPLACE TABLE {{public_dataset}}.forecast_accuracy
OPTIONS (description = 'Forecast accuracy by model, property and days-out bucket. WAPE = sum |error| / sum actual.')
AS
SELECT
    a.model                                                             AS model_code,
    n.model,
    CASE a.property_code WHEN 'CITY' THEN 'City hotel' WHEN 'RESORT' THEN 'Resort hotel'
         WHEN 'ALL' THEN 'Both hotels' ELSE a.property_code END         AS property,
    CASE a.horizon_bucket WHEN 'ALL' THEN 'All horizons'
         ELSE CONCAT(CAST(CAST(SPLIT(a.horizon_bucket, '-')[OFFSET(0)] AS INT64) AS STRING), '-',
                     CAST(CAST(SPLIT(a.horizon_bucket, '-')[OFFSET(1)] AS INT64) AS STRING),
                     ' days out') END                                   AS horizon,
    a.horizon_bucket,
    a.n_nights,
    a.actual_rn,
    ROUND(a.forecast_rn, 1)                                             AS forecast_rn,
    ROUND(a.wape, 4)                                                    AS wape,
    ROUND(a.mae, 1)                                                     AS mae,
    ROUND(a.bias, 4)                                                    AS bias
FROM fc_accuracy a
JOIN (SELECT DISTINCT model_code, model FROM {{public_dataset}}.forecast_nightly) n
  ON n.model_code = a.model;

CREATE OR REPLACE TABLE {{public_dataset}}.booking_pace
OPTIONS (description = 'Reconstructed booking pace: room-nights on the books N days before each stay night, vs the final count, by property, source of business and stay month.')
AS
WITH ev AS (
    SELECT property_code, business_source,
           DATE(DIV(stay_year_month, 100), MOD(stay_year_month, 100), 1) AS stay_month,
           days_before_stay,
           SUM(rn_booked) AS rn_booked,
           SUM(rn_canceled) AS rn_canceled
    FROM mart_booking_curve
    WHERE stay_year_month BETWEEN 201508 AND 201708
    GROUP BY 1, 2, 3, 4
),
final AS (
    SELECT property_code, business_source, stay_month,
           SUM(rn_booked - rn_canceled) AS final_rn
    FROM ev GROUP BY 1, 2, 3
)
SELECT
    CASE e.property_code WHEN 'CITY' THEN 'City hotel' WHEN 'RESORT' THEN 'Resort hotel'
         ELSE e.property_code END                                       AS property,
    e.business_source,
    e.stay_month,
    d.n                                                                 AS days_out,
    SUM(IF(e.days_before_stay >= d.n, e.rn_booked, 0))                  AS gross_booked_rn,
    SUM(IF(e.days_before_stay >= d.n, e.rn_canceled, 0))                AS canceled_rn,
    SUM(IF(e.days_before_stay >= d.n, e.rn_booked - e.rn_canceled, 0))  AS on_books_rn,
    ANY_VALUE(f.final_rn)                                               AS final_rn
FROM ev e
JOIN final f USING (property_code, business_source, stay_month)
CROSS JOIN (SELECT n FROM util_numbers WHERE n <= 365) d
GROUP BY 1, 2, 3, 4;
