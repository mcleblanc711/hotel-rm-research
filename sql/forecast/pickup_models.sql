-- Forecast backtest: classical pickup models, as of one forecast date.
-- Input : fc_otb, fc_final, fc_context
-- Output: fc_dataset         one row per stay night x days out, TRAIN or TEST
--         fc_pickup_curve    pickup by property x day of week x days out
--         fc_forecast_pickup forecasts for every TEST night, three models
--
-- The setup an RM sees: on forecast_date, forecast the final room-nights of every
-- night in the next horizon_days, knowing only what was on the books that day.
--   TRAIN rows: stay nights on or before forecast_date (finals already known),
--               at every days_out from 1 to horizon_days.
--   TEST rows:  each future night once, at days_out = stay_date - forecast_date.
-- Nothing in TRAIN depends on anything after forecast_date.
--
-- Models:
--   OTB_ONLY               no further pickup (a floor, not a forecast)
--   ADDITIVE_PICKUP        OTB + average (final - OTB) at that days out
--   MULTIPLICATIVE_PICKUP  OTB x (sum of finals / sum of OTB) at that days out
-- Both pickup curves are estimated per property and stay day of week.

CREATE OR REPLACE TABLE fc_dataset AS
SELECT
    o.property_code,
    o.stay_date,
    o.days_out,
    CASE WHEN o.days_out <= 7 THEN '001-007'
         WHEN o.days_out <= 14 THEN '008-014'
         WHEN o.days_out <= 30 THEN '015-030'
         WHEN o.days_out <= 60 THEN '031-060'
         WHEN o.days_out <= 90 THEN '061-090'
         ELSE '091-184' END                                      AS horizon_bucket,
    days_between(CAST('1900-01-01' AS DATE), o.stay_date) % 7 + 1 AS stay_dow_iso,
    EXTRACT(MONTH FROM o.stay_date)                               AS stay_month,
    o.otb_rn,
    w.otb_rn                                                      AS otb_rn_7d_earlier,
    f.final_rn,
    CASE WHEN o.stay_date <= c.forecast_date THEN 'TRAIN' ELSE 'TEST' END AS split
FROM fc_otb o
CROSS JOIN fc_context c
JOIN fc_otb w
  ON w.property_code = o.property_code
 AND w.stay_date = o.stay_date
 AND w.days_out = o.days_out + 7
JOIN fc_final f
  ON f.property_code = o.property_code
 AND f.stay_date = o.stay_date
WHERE o.days_out BETWEEN 1 AND c.horizon_days
  AND (o.stay_date <= c.forecast_date
       OR days_between(c.forecast_date, o.stay_date) = o.days_out);

CREATE OR REPLACE TABLE fc_pickup_curve AS
SELECT
    property_code,
    stay_dow_iso,
    days_out,
    COUNT(*)                                                     AS n_train_nights,
    AVG(CAST(final_rn - otb_rn AS DOUBLE))                       AS additive_pickup,
    CAST(SUM(final_rn) AS DOUBLE) / NULLIF(SUM(otb_rn), 0)       AS multiplicative_ratio
FROM fc_dataset
WHERE split = 'TRAIN'
GROUP BY property_code, stay_dow_iso, days_out;

CREATE OR REPLACE TABLE fc_forecast_pickup AS
WITH t AS (
    SELECT d.*, p.additive_pickup, p.multiplicative_ratio
    FROM fc_dataset d
    LEFT JOIN fc_pickup_curve p
      ON p.property_code = d.property_code
     AND p.stay_dow_iso = d.stay_dow_iso
     AND p.days_out = d.days_out
    WHERE d.split = 'TEST'
)
SELECT property_code, stay_date, days_out, horizon_bucket, 'OTB_ONLY' AS model,
       CAST(otb_rn AS DOUBLE) AS forecast_rn,
       CAST(NULL AS DOUBLE) AS lower_rn, CAST(NULL AS DOUBLE) AS upper_rn,
       final_rn AS actual_rn, otb_rn
FROM t
UNION ALL
SELECT property_code, stay_date, days_out, horizon_bucket, 'ADDITIVE_PICKUP',
       GREATEST(otb_rn + COALESCE(additive_pickup, 0), 0),
       NULL, NULL, final_rn, otb_rn
FROM t
UNION ALL
SELECT property_code, stay_date, days_out, horizon_bucket, 'MULTIPLICATIVE_PICKUP',
       otb_rn * COALESCE(multiplicative_ratio, 1),
       NULL, NULL, final_rn, otb_rn
FROM t;
