-- Dialect shim: BigQuery (GoogleSQL).
-- Same contract as duckdb.sql: the two date helpers and a numbers table.
--
-- How scripts/run_bigquery.py uses this file:
--   * It runs the whole file once, which creates util_numbers.
--   * TEMP functions only exist for the job that creates them, so the runner
--     also puts the CREATE TEMP FUNCTION statements at the top of every later
--     job (one job per SQL file).
--   * Everything else in sql/ is written in DuckDB SQL and translated by sqlglot
--     (VARCHAR -> STRING, DOUBLE -> FLOAT64, a % b -> MOD(a, b)), plus one rewrite
--     of the runner's own: CAST(x AS DECIMAL(p, s)) -> ROUND(CAST(x AS NUMERIC), s),
--     because BigQuery allows NUMERIC(p, s) only on columns, not in CAST.

CREATE TEMP FUNCTION add_days(d DATE, n INT64) AS (DATE_ADD(d, INTERVAL n DAY));
CREATE TEMP FUNCTION days_between(d_from DATE, d_to DATE) AS (DATE_DIFF(d_to, d_from, DAY));

-- Numbers table 0..9999, built with plain cross joins like the other dialects.
CREATE OR REPLACE TABLE util_numbers AS
WITH d AS (
    SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
    UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9
)
SELECT a.n + 10 * b.n + 100 * c.n + 1000 * e.n AS n
FROM d a CROSS JOIN d b CROSS JOIN d c CROSS JOIN d e;
