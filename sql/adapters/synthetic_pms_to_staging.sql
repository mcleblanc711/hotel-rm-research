-- Source adapter: synthetic PMS-style export (data/synthetic/pms_export.csv).
-- A template for a real PMS adapter: copy this file, change the column names
-- on the right-hand side, and leave everything downstream untouched.
-- Input : raw_source (all columns as text, plus source_row_number), run_context
-- Output: stg_reservation (same contract as every other adapter)
--
-- What differs from the public dataset, and how the contract absorbs it:
--   * Real reservation numbers  -> source_reservation_id, and a booking_id per ROOM
--     (ResNo + RoomSeq), so multi-room bookings are not flattened.
--   * Numeric status codes 1-5  -> RESERVED / IN_HOUSE / CHECKED_OUT / NO_SHOW / CANCELED.
--   * Real timestamps           -> booking_date and canceled_date are OBSERVED; canceled_at kept.
--   * Group master rows         -> record_type GROUP_MASTER; staged, excluded from the fact.
--   * Observed room revenue     -> room_revenue_observed is filled.
--   * No guest history, parking -> nothing to map; the canonical schema does not need them.

CREATE OR REPLACE TABLE stg_reservation AS
SELECT
    c.source_system,
    r.source_row_number,
    r.ResNo                                                 AS source_reservation_id,
    c.source_system || '-' || r.PropCode || '-' || r.ResNo || '-' || r.RoomSeq
                                                            AS booking_id,
    r.PropCode                                              AS property_code,
    CASE WHEN r.RecType = 'M' THEN 'GROUP_MASTER'
         WHEN NULLIF(r.GroupNo, '') IS NOT NULL THEN 'GROUP_ROOM'
         ELSE 'INDIVIDUAL_ROOM' END                         AS record_type,
    CASE WHEN NULLIF(r.GroupNo, '') IS NOT NULL
         THEN c.source_system || '-' || r.PropCode || '-' || r.GroupNo END
                                                            AS group_id,
    CAST(CAST(r.CreatedOn AS TIMESTAMP) AS DATE)            AS booking_date,
    'OBSERVED'                                              AS booking_date_basis,
    CAST(r.ArrDate AS DATE)                                 AS arrival_date,
    CAST(r.DepDate AS DATE)                                 AS departure_date,
    CASE r.StatusCode
        WHEN '1' THEN 'RESERVED'
        WHEN '2' THEN 'IN_HOUSE'
        WHEN '3' THEN 'CHECKED_OUT'
        WHEN '4' THEN 'NO_SHOW'
        WHEN '5' THEN 'CANCELED'
        ELSE 'UNKNOWN'
    END                                                     AS reservation_status,
    r.StatusCode                                            AS reservation_status_raw,
    CAST(NULL AS DATE)                                      AS status_date,
    CASE WHEN r.StatusCode = '5'
         THEN CAST(CAST(NULLIF(r.CancelledOn, '') AS TIMESTAMP) AS DATE) END
                                                            AS canceled_date,
    CASE WHEN r.StatusCode = '5' THEN CAST(NULLIF(r.CancelledOn, '') AS TIMESTAMP) END
                                                            AS canceled_at,
    CASE WHEN r.StatusCode = '5' AND NULLIF(r.CancelledOn, '') IS NOT NULL THEN 'OBSERVED'
         ELSE 'UNAVAILABLE' END                             AS cancellation_date_basis,
    r.MktSeg                                                AS market_segment_raw,
    CAST(NULL AS VARCHAR)                                   AS distribution_channel_raw,
    CAST(NULL AS VARCHAR)                                   AS agent_raw,
    CAST(NULL AS VARCHAR)                                   AS company_raw,
    r.RoomTypeBooked                                        AS reserved_room_type,
    NULLIF(r.RoomTypeAssigned, '')                          AS assigned_room_type,
    CAST(r.Adults AS INTEGER)                               AS adults,
    CAST(r.Kids AS INTEGER)                                 AS children,
    CAST(NULL AS INTEGER)                                   AS babies,
    CAST(r.RateAmt AS DECIMAL(12, 2))                       AS adr,
    r.Currency                                              AS currency,
    CAST(r.RoomRevTotal AS DECIMAL(14, 2))                  AS room_revenue_observed,
    CAST(NULL AS VARCHAR)                                   AS deposit_type_raw,
    CAST(NULL AS VARCHAR)                                   AS customer_type_raw
FROM raw_source r
CROSS JOIN run_context c;
