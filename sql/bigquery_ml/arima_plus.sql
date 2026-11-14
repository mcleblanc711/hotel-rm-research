-- BigQuery ML: ARIMA_PLUS time-series forecast of final room-nights.
-- GoogleSQL, BigQuery only. Run by scripts/bigquery_forecast_dashboard.py,
-- which replaces {{horizon_days}} from the source's forecast settings.
-- Input : fc_final, fc_context, fc_dataset
-- Output: model fc_model_arima, table fc_forecast_arima
--
-- One series per property: the final count of every night from train_start to
-- forecast_date. ARIMA_PLUS picks the ARIMA order, weekly and yearly seasonality,
-- and Portuguese holiday effects itself. It never sees what is on the books, so it
-- shows what a pure time-series forecast misses compared with pickup models.
-- 80% prediction intervals go to lower_rn / upper_rn.

CREATE OR REPLACE MODEL fc_model_arima
OPTIONS (
    model_type = 'ARIMA_PLUS',
    time_series_timestamp_col = 'stay_date',
    time_series_data_col = 'final_rn',
    time_series_id_col = 'property_code',
    data_frequency = 'DAILY',
    holiday_region = 'PT',
    horizon = {{horizon_days}}
) AS
SELECT f.property_code, f.stay_date, f.final_rn
FROM fc_final f
CROSS JOIN fc_context c
WHERE f.stay_date BETWEEN c.train_start AND c.forecast_date;

CREATE OR REPLACE TABLE fc_forecast_arima AS
SELECT
    t.property_code, t.stay_date, t.days_out, t.horizon_bucket,
    'BQML_ARIMA_PLUS'                         AS model,
    GREATEST(f.forecast_value, 0)             AS forecast_rn,
    f.prediction_interval_lower_bound         AS lower_rn,
    f.prediction_interval_upper_bound         AS upper_rn,
    t.final_rn                                AS actual_rn,
    t.otb_rn
FROM ML.FORECAST(MODEL fc_model_arima,
                 STRUCT({{horizon_days}} AS horizon, 0.8 AS confidence_level)) f
JOIN fc_dataset t
  ON t.split = 'TEST'
 AND t.property_code = f.property_code
 AND t.stay_date = DATE(f.forecast_timestamp);
