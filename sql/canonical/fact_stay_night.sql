-- Canonical: fact_stay_night. Grain: one scheduled room-night per room booking.
-- A row here means "this night was booked", NOT "this room was occupied":
-- canceled and no-show bookings keep their scheduled nights.
-- Zero-night bookings produce no rows.
-- Explosion is a join to util_numbers so it works in any SQL dialect.

CREATE OR REPLACE TABLE fact_stay_night AS
SELECT
    f.booking_id || '-' || LPAD(CAST(n.n + 1 AS VARCHAR), 3, '0') AS stay_night_id,
    f.booking_id,
    f.property_code,
    add_days(f.arrival_date, n.n)        AS stay_date,
    n.n + 1                              AS night_index,
    f.los_nights,
    f.reserved_room_type,
    f.assigned_room_type,
    f.reservation_status,
    f.business_source,
    f.booking_date,
    f.canceled_date,
    1                                    AS room_nights,
    CAST(f.room_revenue / f.los_nights AS DECIMAL(14, 4)) AS allocated_room_revenue,
    CASE WHEN f.room_revenue_basis = 'OBSERVED' THEN 'EVEN_SPLIT_OF_OBSERVED'
         ELSE 'ADR_DERIVED_ALLOCATION' END AS nightly_rate_basis
FROM fact_reservation f
JOIN util_numbers n
  ON n.n < f.los_nights
WHERE f.los_nights > 0;
