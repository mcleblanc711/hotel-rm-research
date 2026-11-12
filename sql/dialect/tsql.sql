-- Dialect shim: SQL Server (T-SQL).
-- STATUS: UNTESTED. Written for reference; it has not been executed against a
-- SQL Server instance. Run the QA scripts after porting and compare totals.
--
-- Porting notes for the canonical scripts:
--   1. Call the helpers with a schema prefix: dbo.add_days(...), dbo.days_between(...).
--   2. Replace "CREATE OR REPLACE TABLE x AS SELECT ..." with
--      "DROP TABLE IF EXISTS x; SELECT ... INTO x FROM ...".
--   3. String concatenation "a || b" becomes CONCAT(a, b).
--   4. LPAD(x, 6, '0') becomes RIGHT(CONCAT('000000', x), 6).
GO
CREATE OR ALTER FUNCTION dbo.add_days (@d DATE, @n INT) RETURNS DATE AS
BEGIN
    RETURN DATEADD(DAY, @n, @d);
END;
GO
CREATE OR ALTER FUNCTION dbo.days_between (@d_from DATE, @d_to DATE) RETURNS INT AS
BEGIN
    RETURN DATEDIFF(DAY, @d_from, @d_to);
END;
GO
DROP TABLE IF EXISTS util_numbers;
WITH d AS (
    SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
    UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9
)
SELECT a.n + 10 * b.n + 100 * c.n + 1000 * e.n AS n
INTO util_numbers
FROM d a CROSS JOIN d b CROSS JOIN d c CROSS JOIN d e;
GO
