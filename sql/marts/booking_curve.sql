-- Mart: booking curve by stay night.
-- Grain: property x stay year-month x stay day-of-week x business source x
--        days_before_stay (only days on which something happened).
--
--   rn_booked     room-nights booked exactly N days before the stay night
--   rn_canceled   room-nights canceled exactly N days before the stay night
--   rn_stayed     of rn_booked, the room-nights that ended as CHECKED_OUT
--   rev_booked / rev_canceled   allocated room revenue of the above
--   cum_gross     room-nights ever booked by N days out
--   cum_canceled  room-nights canceled by N days out
--   net_otb       cum_gross - cum_canceled  (rooms on the books at N days out)
--
-- To aggregate across rows (several months, sources...), sum the event columns
-- with a "days_before_stay >= N" condition. The cum_* columns are only valid
-- within a single row group.
--
-- PROVENANCE: on sources without modification history this is a RECONSTRUCTED
-- curve built from each booking's final state, not an observed OTB snapshot.
-- No-shows count as on the books (they were, until the night itself).
-- Stay nights after as_of_date are flagged so partial curves are not misread.

CREATE OR REPLACE TABLE mart_booking_curve AS
WITH ev AS (
    SELECT
        n.property_code,
        n.stay_date,
        n.business_source,
        days_between(n.booking_date, n.stay_date) AS days_before_stay,
        n.room_nights AS rn_booked,
        0             AS rn_canceled,
        CASE WHEN n.reservation_status = 'CHECKED_OUT' THEN n.room_nights ELSE 0 END AS rn_stayed,
        n.allocated_room_revenue AS rev_booked,
        0             AS rev_canceled
    FROM fact_stay_night n
    UNION ALL
    SELECT
        n.property_code,
        n.stay_date,
        n.business_source,
        days_between(n.canceled_date, n.stay_date) AS days_before_stay,
        0,
        n.room_nights,
        0,
        0,
        n.allocated_room_revenue
    FROM fact_stay_night n
    WHERE n.canceled_date IS NOT NULL
),
agg AS (
    SELECT
        ev.property_code,
        EXTRACT(YEAR FROM ev.stay_date) * 100 + EXTRACT(MONTH FROM ev.stay_date) AS stay_year_month,
        days_between(CAST('1900-01-01' AS DATE), ev.stay_date) % 7 + 1          AS stay_dow_iso,
        ev.business_source,
        CASE WHEN ev.days_before_stay < 0 THEN 0 ELSE ev.days_before_stay END    AS days_before_stay,
        MAX(CASE WHEN ev.stay_date > c.as_of_date THEN 1 ELSE 0 END)             AS has_future_nights,
        SUM(ev.rn_booked)    AS rn_booked,
        SUM(ev.rn_canceled)  AS rn_canceled,
        SUM(ev.rn_stayed)    AS rn_stayed,
        SUM(ev.rev_booked)   AS rev_booked,
        SUM(ev.rev_canceled) AS rev_canceled
    FROM ev
    CROSS JOIN run_context c
    GROUP BY 1, 2, 3, 4, 5
)
SELECT
    a.*,
    SUM(a.rn_booked)   OVER w AS cum_gross,
    SUM(a.rn_canceled) OVER w AS cum_canceled,
    SUM(a.rn_booked - a.rn_canceled) OVER w AS net_otb
FROM agg a
WINDOW w AS (
    PARTITION BY a.property_code, a.stay_year_month, a.stay_dow_iso, a.business_source
    ORDER BY a.days_before_stay DESC
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
);

-- Compact version for Excel: weekend flag instead of day of week, and
-- days_before_stay capped at 366 ("366 or more"). Event columns only.
CREATE OR REPLACE TABLE mart_booking_curve_compact AS
SELECT
    property_code,
    stay_year_month,
    CASE WHEN stay_dow_iso IN (5, 6) THEN 1 ELSE 0 END           AS is_fri_sat,
    business_source,
    CASE WHEN days_before_stay > 366 THEN 366 ELSE days_before_stay END AS days_before_stay,
    SUM(rn_booked)    AS rn_booked,
    SUM(rn_canceled)  AS rn_canceled,
    SUM(rn_stayed)    AS rn_stayed,
    SUM(rev_booked)   AS rev_booked,
    SUM(rev_canceled) AS rev_canceled
FROM mart_booking_curve
GROUP BY 1, 2, 3, 4, 5;
