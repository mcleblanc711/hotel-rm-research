-- Source adapter: Antonio, Almeida & Nunes (2019) Hotel Booking Demand.
-- This is the ONLY file that knows the public dataset's column names.
-- Input : raw_source (all columns as text, plus source_row_number), run_context
-- Output: stg_reservation (the staging contract every adapter must produce)
--
-- Rules:
--   * No rows dropped, no de-duplication (identical rows may be distinct bookings).
--   * booking_date is DERIVED (arrival - lead_time), not observed.
--   * Only 'Canceled' rows get a canceled_date. 'No-Show' rows do not.
--   * The source's own is_canceled column is NOT used here (QA cross-check only).

CREATE OR REPLACE TABLE stg_reservation AS
WITH typed AS (
    SELECT
        r.source_row_number,
        r.hotel,
        CAST(
            r.arrival_date_year || '-' ||
            CASE r.arrival_date_month
                WHEN 'January' THEN '01' WHEN 'February' THEN '02' WHEN 'March' THEN '03'
                WHEN 'April' THEN '04' WHEN 'May' THEN '05' WHEN 'June' THEN '06'
                WHEN 'July' THEN '07' WHEN 'August' THEN '08' WHEN 'September' THEN '09'
                WHEN 'October' THEN '10' WHEN 'November' THEN '11' WHEN 'December' THEN '12'
            END || '-' ||
            LPAD(r.arrival_date_day_of_month, 2, '0')
        AS DATE) AS arrival_date,
        CAST(r.stays_in_weekend_nights AS INTEGER) + CAST(r.stays_in_week_nights AS INTEGER) AS nights,
        CAST(r.lead_time AS INTEGER) AS lead_time,
        r.reservation_status,
        CAST(r.reservation_status_date AS DATE) AS reservation_status_date,
        r.market_segment,
        r.distribution_channel,
        r.agent,
        r.company,
        r.reserved_room_type,
        r.assigned_room_type,
        r.adults,
        r.children,
        r.babies,
        CAST(r.adr AS DECIMAL(12, 2)) AS adr,
        r.deposit_type,
        r.customer_type
    FROM raw_source r
)
SELECT
    c.source_system,
    t.source_row_number,
    CAST(NULL AS VARCHAR)                                   AS source_reservation_id,
    c.source_system || '-' || SUBSTR(c.source_fingerprint, 1, 8) || '-' ||
        LPAD(CAST(t.source_row_number AS VARCHAR), 6, '0')  AS booking_id,
    CASE t.hotel WHEN 'City Hotel' THEN 'CITY' WHEN 'Resort Hotel' THEN 'RESORT' ELSE t.hotel END
                                                            AS property_code,
    'INDIVIDUAL_ROOM'                                       AS record_type,
    CAST(NULL AS VARCHAR)                                   AS group_id,
    add_days(t.arrival_date, -t.lead_time)                  AS booking_date,
    'DERIVED'                                               AS booking_date_basis,
    t.arrival_date,
    add_days(t.arrival_date, t.nights)                      AS departure_date,
    CASE t.reservation_status
        WHEN 'Check-Out' THEN 'CHECKED_OUT'
        WHEN 'No-Show'   THEN 'NO_SHOW'
        WHEN 'Canceled'  THEN 'CANCELED'
        ELSE 'UNKNOWN'
    END                                                     AS reservation_status,
    t.reservation_status                                    AS reservation_status_raw,
    t.reservation_status_date                               AS status_date,
    CASE WHEN t.reservation_status = 'Canceled' THEN t.reservation_status_date END
                                                            AS canceled_date,
    CASE WHEN t.reservation_status = 'Canceled' THEN 'OBSERVED' ELSE 'UNAVAILABLE' END
                                                            AS cancellation_date_basis,
    t.market_segment                                        AS market_segment_raw,
    t.distribution_channel                                  AS distribution_channel_raw,
    NULLIF(t.agent, 'NULL')                                 AS agent_raw,
    NULLIF(t.company, 'NULL')                               AS company_raw,
    t.reserved_room_type,
    t.assigned_room_type,
    CAST(t.adults AS INTEGER)                               AS adults,
    CAST(NULLIF(t.children, 'NA') AS INTEGER)               AS children,
    CAST(t.babies AS INTEGER)                               AS babies,
    t.adr,
    'EUR'                                                   AS currency,
    CAST(NULL AS DECIMAL(14, 2))                            AS room_revenue_observed,
    t.deposit_type                                          AS deposit_type_raw,
    t.customer_type                                         AS customer_type_raw
FROM typed t
CROSS JOIN run_context c;

-- Optional source-specific extras. NOT part of the canonical schema: a private
-- PMS may have no guest history or parking data, so nothing core may read this.
CREATE OR REPLACE TABLE ext_antonio_reservation AS
SELECT
    s.booking_id,
    CAST(r.is_canceled AS INTEGER)                    AS src_is_canceled,
    CAST(r.is_repeated_guest AS INTEGER)              AS is_repeated_guest,
    CAST(r.previous_cancellations AS INTEGER)         AS previous_cancellations,
    CAST(r.previous_bookings_not_canceled AS INTEGER) AS previous_bookings_not_canceled,
    CAST(r.booking_changes AS INTEGER)                AS booking_changes,
    CAST(r.days_in_waiting_list AS INTEGER)           AS days_in_waiting_list,
    CAST(r.required_car_parking_spaces AS INTEGER)    AS required_car_parking_spaces,
    CAST(r.total_of_special_requests AS INTEGER)      AS total_of_special_requests,
    r.meal,
    r.country
FROM raw_source r
JOIN stg_reservation s ON s.source_row_number = r.source_row_number;
