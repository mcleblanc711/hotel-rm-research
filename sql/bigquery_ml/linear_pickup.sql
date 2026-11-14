-- BigQuery ML: linear regression that learns its own pickup curve.
-- GoogleSQL, BigQuery only. Run by scripts/bigquery_forecast_dashboard.py.
-- Input : fc_dataset (sql/forecast/pickup_models.sql)
-- Output: model fc_model_linear, table fc_forecast_linear
--
-- The classical models pick one form: final = OTB + pickup (additive) or
-- final = OTB x ratio (multiplicative). This model fits both at once:
--   final ~ ratio[horizon] x OTB              (one OTB weight per horizon bucket)
--         + intercepts by property x horizon, property x day of week,
--           property x month                  (additive pickup and seasonality)
--         + weight x pickup in the last 7 days (pace momentum)
-- TRANSFORM keeps the feature engineering inside the model, so ML.PREDICT
-- applies exactly the same steps to the test rows.
-- LINEAR_REG is a built-in model: billed at 50x the bytes read, and the input is
-- a few MB. (Boosted trees train on Vertex AI and cannot be cost-estimated first.)

CREATE OR REPLACE MODEL fc_model_linear
TRANSFORM (
    final_rn,
    CONCAT(property_code, '_', horizon_bucket)                    AS property_horizon,
    CONCAT(property_code, '_dow', CAST(stay_dow_iso AS STRING))   AS property_dow,
    CONCAT(property_code, '_m', CAST(stay_month AS STRING))       AS property_month,
    IF(horizon_bucket = '001-007', otb_rn, 0)                     AS otb_001_007,
    IF(horizon_bucket = '008-014', otb_rn, 0)                     AS otb_008_014,
    IF(horizon_bucket = '015-030', otb_rn, 0)                     AS otb_015_030,
    IF(horizon_bucket = '031-060', otb_rn, 0)                     AS otb_031_060,
    IF(horizon_bucket = '061-090', otb_rn, 0)                     AS otb_061_090,
    IF(horizon_bucket = '091-184', otb_rn, 0)                     AS otb_091_184,
    otb_rn - otb_rn_7d_earlier                                    AS pickup_last_7d
)
OPTIONS (
    model_type = 'LINEAR_REG',
    input_label_cols = ['final_rn'],
    data_split_method = 'NO_SPLIT',
    l2_reg = 1.0
) AS
SELECT * FROM fc_dataset WHERE split = 'TRAIN';

CREATE OR REPLACE TABLE fc_forecast_linear AS
SELECT
    property_code, stay_date, days_out, horizon_bucket,
    'BQML_LINEAR_REG'                    AS model,
    GREATEST(predicted_final_rn, 0)      AS forecast_rn,
    CAST(NULL AS FLOAT64)                AS lower_rn,
    CAST(NULL AS FLOAT64)                AS upper_rn,
    final_rn                             AS actual_rn,
    otb_rn
FROM ML.PREDICT(MODEL fc_model_linear, (SELECT * FROM fc_dataset WHERE split = 'TEST'));
