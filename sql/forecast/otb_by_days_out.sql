-- Forecast input: room-nights on the books (OTB) for every stay night at every
-- number of days out, plus each night's final count.
-- Input : fact_stay_night, fc_context (train_start, forecast_date, horizon_days)
-- Output: fc_otb   (property_code, stay_date, days_out, otb_rn)
--         fc_final (property_code, stay_date, final_rn)
--
-- OTB at d days out = room-nights booked on or before (stay_date - d) minus those
-- canceled on or before it: what the hotel saw at the end of that day. No-shows
-- stay on the books. final_rn is OTB at d = 0, the count on the night itself.
-- A booking or cancellation dated after the stay night counts at d = 0.
--
-- PROVENANCE: on sources without modification history (the public dataset) this
-- is reconstructed from each booking's final state, like the booking-curve mart.
--
-- The grid is every property x every date from train_start to the end of the
-- forecast window, so a night with no bookings at all still appears (as 0).
-- days_out runs to horizon_days + 7 so the "OTB a week earlier" feature exists
-- for every forecast row.

CREATE OR REPLACE TABLE fc_otb AS
WITH ev AS (
    SELECT property_code, stay_date,
           CASE WHEN days_between(booking_date, stay_date) < 0 THEN 0
                ELSE days_between(booking_date, stay_date) END AS days_before,
           room_nights AS rn_change
    FROM fact_stay_night
    UNION ALL
    SELECT property_code, stay_date,
           CASE WHEN days_between(canceled_date, stay_date) < 0 THEN 0
                ELSE days_between(canceled_date, stay_date) END AS days_before,
           0 - room_nights AS rn_change
    FROM fact_stay_night
    WHERE canceled_date IS NOT NULL
),
ev_agg AS (
    SELECT property_code, stay_date, days_before, SUM(rn_change) AS rn_change
    FROM ev
    GROUP BY property_code, stay_date, days_before
),
nights AS (
    SELECT p.property_code, add_days(c.train_start, n.n) AS stay_date
    FROM (SELECT DISTINCT property_code FROM fact_stay_night) p
    CROSS JOIN fc_context c
    JOIN util_numbers n
      ON n.n <= days_between(c.train_start, add_days(c.forecast_date, c.horizon_days))
)
SELECT s.property_code,
       s.stay_date,
       d.n                          AS days_out,
       COALESCE(SUM(e.rn_change), 0) AS otb_rn
FROM nights s
CROSS JOIN fc_context c
JOIN util_numbers d
  ON d.n <= c.horizon_days + 7
LEFT JOIN ev_agg e
  ON e.property_code = s.property_code
 AND e.stay_date = s.stay_date
 AND e.days_before >= d.n
GROUP BY s.property_code, s.stay_date, d.n;

CREATE OR REPLACE TABLE fc_final AS
SELECT property_code, stay_date, otb_rn AS final_rn
FROM fc_otb
WHERE days_out = 0;
