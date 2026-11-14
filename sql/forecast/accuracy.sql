-- Forecast accuracy by model, property and horizon, with roll-ups.
-- Input : fc_forecast (the runner unions every fc_forecast_* table into it)
-- Output: fc_accuracy
--
--   wape  sum |forecast - actual| / sum actual   (weighted absolute % error)
--   mae   mean |forecast - actual|, in room-nights per night
--   bias  (sum forecast - sum actual) / sum actual; negative = under-forecast
-- WAPE rather than MAPE: MAPE explodes on low-demand nights.
-- property_code / horizon_bucket = 'ALL' rows are roll-ups.

-- The roll-up labels are applied outside the grouping on purpose. Written as
-- COALESCE(property_code, 'ALL') AS property_code in the same SELECT, BigQuery
-- resolves property_code in GROUPING SETS to the alias and DuckDB to the column,
-- and the two engines disagree (caught by the cross-engine comparison).

CREATE OR REPLACE TABLE fc_accuracy AS
SELECT
    g.model,
    COALESCE(g.property_code, 'ALL')                        AS property_code,
    COALESCE(g.horizon_bucket, 'ALL')                       AS horizon_bucket,
    g.n_nights,
    g.actual_rn,
    g.forecast_rn,
    g.abs_error_rn / NULLIF(g.actual_rn, 0)                 AS wape,
    g.abs_error_rn / g.n_nights                             AS mae,
    (g.forecast_rn - g.actual_rn) / NULLIF(g.actual_rn, 0)  AS bias
FROM (
    SELECT
        model,
        property_code,
        horizon_bucket,
        COUNT(*)                          AS n_nights,
        SUM(actual_rn)                    AS actual_rn,
        SUM(forecast_rn)                  AS forecast_rn,
        SUM(ABS(forecast_rn - actual_rn)) AS abs_error_rn
    FROM fc_forecast
    GROUP BY GROUPING SETS (
        (model, property_code, horizon_bucket),
        (model, horizon_bucket),
        (model, property_code),
        (model)
    )
) g;
