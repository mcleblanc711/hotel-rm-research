-- Structural QA: must all pass. A FATAL failure stops the pipeline.
-- Each check returns: check_name, severity, observed, expected, description.
-- The runner unions every qa_* table into qa_results and adds passed (1/0).
-- Each QA file creates its own table instead of INSERTing into a shared one,
-- so the whole pipeline is DDL-only (CREATE ... AS SELECT). That runs on
-- engines without DML too, such as the BigQuery sandbox.

CREATE OR REPLACE TABLE qa_structural AS
SELECT 'booking_id_unique' AS check_name, 'FATAL' AS severity,
       CAST(COUNT(*) - COUNT(DISTINCT booking_id) AS DOUBLE) AS observed,
       CAST(0 AS DOUBLE) AS expected,
       'Duplicate canonical booking IDs' AS description
FROM fact_reservation
UNION ALL
SELECT 'source_rows_reconcile', 'FATAL',
       CAST((SELECT COUNT(*) FROM raw_source) AS DOUBLE),
       CAST((SELECT COUNT(*) FROM fact_reservation)
          + (SELECT COUNT(*) FROM stg_reservation WHERE record_type = 'GROUP_MASTER') AS DOUBLE),
       'Source rows = canonical reservations + staged group masters'
UNION ALL
SELECT 'stay_nights_equal_sum_los', 'FATAL',
       CAST((SELECT COUNT(*) FROM fact_stay_night) AS DOUBLE),
       CAST((SELECT COALESCE(SUM(los_nights), 0) FROM fact_reservation WHERE los_nights > 0) AS DOUBLE),
       'Stay-night rows = sum of scheduled nights'
UNION ALL
SELECT 'stay_night_orphans', 'FATAL',
       CAST(COUNT(*) AS DOUBLE), CAST(0 AS DOUBLE),
       'Stay-nights without a parent reservation'
FROM fact_stay_night n
LEFT JOIN fact_reservation f ON f.booking_id = n.booking_id
WHERE f.booking_id IS NULL
UNION ALL
SELECT 'stay_date_outside_interval', 'FATAL',
       CAST(COUNT(*) AS DOUBLE), CAST(0 AS DOUBLE),
       'Stay dates before arrival or on/after departure'
FROM fact_stay_night n
JOIN fact_reservation f ON f.booking_id = n.booking_id
WHERE n.stay_date < f.arrival_date OR n.stay_date >= f.departure_date
UNION ALL
SELECT 'zero_night_bookings_have_no_nights', 'FATAL',
       CAST(COUNT(*) AS DOUBLE), CAST(0 AS DOUBLE),
       'Stay-nights belonging to zero-night bookings'
FROM fact_stay_night n
JOIN fact_reservation f ON f.booking_id = n.booking_id
WHERE f.los_nights <= 0
UNION ALL
SELECT 'negative_los', 'FATAL',
       CAST(COUNT(*) AS DOUBLE), CAST(0 AS DOUBLE),
       'Departure before arrival'
FROM fact_reservation WHERE los_nights < 0
UNION ALL
SELECT 'allocated_revenue_reconciles', 'FATAL',
       CAST(ROUND((SELECT COALESCE(SUM(allocated_room_revenue), 0) FROM fact_stay_night), 0) AS DOUBLE),
       CAST(ROUND((SELECT COALESCE(SUM(room_revenue), 0) FROM fact_reservation WHERE los_nights > 0), 0) AS DOUBLE),
       'Nightly allocations sum to reservation-level room revenue (to the nearest unit)'
UNION ALL
SELECT 'unknown_status', 'FATAL',
       CAST(COUNT(*) AS DOUBLE), CAST(0 AS DOUBLE),
       'Statuses outside RESERVED / IN_HOUSE / CHECKED_OUT / NO_SHOW / CANCELED'
FROM fact_reservation
WHERE reservation_status NOT IN ('RESERVED', 'IN_HOUSE', 'CHECKED_OUT', 'NO_SHOW', 'CANCELED')
UNION ALL
SELECT 'group_master_in_fact', 'FATAL',
       CAST(COUNT(*) AS DOUBLE), CAST(0 AS DOUBLE),
       'Group master records leaking into fact_reservation'
FROM fact_reservation WHERE record_type = 'GROUP_MASTER'
UNION ALL
SELECT 'canceled_without_status', 'FATAL',
       CAST(COUNT(*) AS DOUBLE), CAST(0 AS DOUBLE),
       'canceled_date present on a booking whose status is not CANCELED'
FROM fact_reservation
WHERE canceled_date IS NOT NULL AND reservation_status <> 'CANCELED';
