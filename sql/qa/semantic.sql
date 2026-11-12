-- Semantic QA: warnings. Unusual rows are reported and kept, never deleted.
-- expected is NULL: these are counts to review, not pass/fail equations.

INSERT INTO qa_results
SELECT 'negative_adr', 'WARN', CAST(COUNT(*) AS DOUBLE), CAST(NULL AS DOUBLE), 'Bookings with ADR < 0'
FROM fact_reservation WHERE adr < 0
UNION ALL
SELECT 'zero_adr', 'WARN', CAST(COUNT(*) AS DOUBLE), NULL, 'Bookings with ADR = 0'
FROM fact_reservation WHERE adr = 0
UNION ALL
SELECT 'zero_night_bookings', 'WARN', CAST(COUNT(*) AS DOUBLE), NULL, 'Bookings with zero scheduled nights (kept; no stay-nights)'
FROM fact_reservation WHERE los_nights = 0
UNION ALL
SELECT 'long_stays_over_30', 'WARN', CAST(COUNT(*) AS DOUBLE), NULL, 'Bookings longer than 30 nights'
FROM fact_reservation WHERE los_nights > 30
UNION ALL
SELECT 'zero_guests', 'WARN', CAST(COUNT(*) AS DOUBLE), NULL, 'Bookings reporting zero guests'
FROM fact_reservation WHERE COALESCE(adults, 0) + COALESCE(children, 0) + COALESCE(babies, 0) = 0
UNION ALL
SELECT 'missing_guest_counts', 'WARN', CAST(COUNT(*) AS DOUBLE), NULL, 'Bookings with a missing adult or child count'
FROM fact_reservation WHERE adults IS NULL OR children IS NULL
UNION ALL
SELECT 'negative_booking_lead', 'WARN', CAST(COUNT(*) AS DOUBLE), NULL, 'Booking date after arrival date'
FROM fact_reservation WHERE booking_lead_days < 0
UNION ALL
SELECT 'cancel_after_arrival', 'WARN', CAST(COUNT(*) AS DOUBLE), NULL, 'Canceled bookings with cancellation date after arrival'
FROM fact_reservation WHERE cancellation_lead_days < 0
UNION ALL
SELECT 'cancel_before_booking', 'WARN', CAST(COUNT(*) AS DOUBLE), NULL, 'Cancellation date earlier than booking date'
FROM fact_reservation WHERE canceled_date < booking_date
UNION ALL
SELECT 'canceled_missing_date', 'WARN', CAST(COUNT(*) AS DOUBLE), NULL, 'CANCELED bookings with no cancellation date'
FROM fact_reservation WHERE reservation_status = 'CANCELED' AND canceled_date IS NULL
UNION ALL
SELECT 'unmapped_business_source', 'WARN', CAST(COUNT(*) AS DOUBLE), NULL, 'Bookings whose raw segment has no row in dim_source_mapping'
FROM fact_reservation f
LEFT JOIN dim_source_mapping m
       ON m.source_system = f.source_system AND m.market_segment_raw = f.market_segment_raw
WHERE m.business_source IS NULL
UNION ALL
SELECT 'identical_looking_rows', 'WARN', CAST(COALESCE(SUM(c - 1), 0) AS DOUBLE), NULL,
       'Bookings identical to another on property/dates/status/segment/room/ADR (kept; cannot be proven duplicates)'
FROM (
    SELECT COUNT(*) AS c
    FROM fact_reservation
    GROUP BY property_code, booking_date, arrival_date, departure_date, reservation_status, status_date,
             market_segment_raw, distribution_channel_raw, agent_raw, company_raw,
             reserved_room_type, assigned_room_type, adults, children, babies, adr,
             deposit_type_raw, customer_type_raw
    HAVING COUNT(*) > 1
) d;
