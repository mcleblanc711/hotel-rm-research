-- Dialect shim: DuckDB.
-- The canonical SQL only uses these two date helpers, so porting to another
-- engine means re-implementing this one file (see tsql.sql).
CREATE OR REPLACE MACRO add_days(d, n) AS CAST(d AS DATE) + CAST(n AS INTEGER);
CREATE OR REPLACE MACRO days_between(d_from, d_to) AS CAST(CAST(d_to AS DATE) - CAST(d_from AS DATE) AS INTEGER);

-- Numbers table 0..9999, built with plain cross joins (no generate_series).
CREATE OR REPLACE TABLE util_numbers AS
WITH d AS (
    SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
    UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9
)
SELECT a.n + 10 * b.n + 100 * c.n + 1000 * e.n AS n
FROM d a CROSS JOIN d b CROSS JOIN d c CROSS JOIN d e;
