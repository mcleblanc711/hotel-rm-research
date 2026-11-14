-- Source-specific QA for the public dataset: verifies the profile reported in
-- earlier design notes instead of trusting it. Mismatches are WARN, not FATAL,
-- because the numbers below are claims to test, not rules.

CREATE OR REPLACE TABLE qa_antonio_profile AS
SELECT 'antonio_total_rows' AS check_name, 'WARN' AS severity, CAST(COUNT(*) AS DOUBLE) AS observed,
       CAST(119390 AS DOUBLE) AS expected, 'Reported total records' AS description
FROM fact_reservation
UNION ALL
SELECT 'antonio_city_rows', 'WARN', CAST(COUNT(*) AS DOUBLE), 79330, 'Reported City Hotel bookings'
FROM fact_reservation WHERE property_code = 'CITY'
UNION ALL
SELECT 'antonio_resort_rows', 'WARN', CAST(COUNT(*) AS DOUBLE), 40060, 'Reported Resort Hotel bookings'
FROM fact_reservation WHERE property_code = 'RESORT'
UNION ALL
SELECT 'antonio_checked_out', 'WARN', CAST(COUNT(*) AS DOUBLE), 75166, 'Reported Check-Out records'
FROM fact_reservation WHERE reservation_status = 'CHECKED_OUT'
UNION ALL
SELECT 'antonio_canceled', 'WARN', CAST(COUNT(*) AS DOUBLE), 43017, 'Reported Canceled records'
FROM fact_reservation WHERE reservation_status = 'CANCELED'
UNION ALL
SELECT 'antonio_no_show', 'WARN', CAST(COUNT(*) AS DOUBLE), 1207, 'Reported No-Show records'
FROM fact_reservation WHERE reservation_status = 'NO_SHOW'
UNION ALL
SELECT 'antonio_scheduled_room_nights', 'WARN', CAST(COUNT(*) AS DOUBLE), 409257, 'Reported scheduled room-nights'
FROM fact_stay_night
UNION ALL
SELECT 'antonio_checked_out_room_nights', 'WARN', CAST(COUNT(*) AS DOUBLE), 255040, 'Reported room-nights on Check-Out records'
FROM fact_stay_night WHERE reservation_status = 'CHECKED_OUT'
UNION ALL
SELECT 'antonio_zero_night', 'WARN', CAST(COUNT(*) AS DOUBLE), 715, 'Reported zero-night records'
FROM fact_reservation WHERE los_nights = 0
UNION ALL
SELECT 'antonio_zero_adr', 'WARN', CAST(COUNT(*) AS DOUBLE), 1959, 'Reported zero-ADR observations'
FROM fact_reservation WHERE adr = 0
UNION ALL
SELECT 'antonio_cancel_on_arrival_day', 'WARN', CAST(COUNT(*) AS DOUBLE), 881, 'Reported cancellations on the arrival date'
FROM fact_reservation WHERE reservation_status = 'CANCELED' AND cancellation_lead_days = 0
UNION ALL
SELECT 'antonio_src_is_canceled_agrees', 'WARN', CAST(COUNT(*) AS DOUBLE), 0,
       'Rows where source is_canceled disagrees with status in (CANCELED, NO_SHOW)'
FROM fact_reservation f
JOIN ext_antonio_reservation e ON e.booking_id = f.booking_id
WHERE e.src_is_canceled <> CASE WHEN f.reservation_status IN ('CANCELED', 'NO_SHOW') THEN 1 ELSE 0 END;
