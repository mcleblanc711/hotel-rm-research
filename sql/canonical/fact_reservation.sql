-- Canonical: fact_reservation. Grain: one row per individual room booking.
-- Source-agnostic: reads only stg_reservation, dim_source_mapping, run_context.
-- Group masters stay in stg_reservation and are excluded here so they cannot
-- inflate room-night demand.

CREATE OR REPLACE TABLE fact_reservation AS
SELECT
    s.booking_id,
    s.source_system,
    s.source_row_number,
    s.source_reservation_id,
    s.property_code,
    s.record_type,
    s.group_id,
    s.booking_date,
    s.booking_date_basis,
    s.arrival_date,
    s.departure_date,
    days_between(s.arrival_date, s.departure_date)          AS los_nights,
    days_between(s.booking_date, s.arrival_date)            AS booking_lead_days,
    s.reservation_status,
    s.reservation_status_raw,
    s.status_date,
    CASE WHEN s.reservation_status = 'CANCELED' THEN 1 ELSE 0 END AS is_canceled,
    s.canceled_date,
    s.cancellation_date_basis,
    days_between(s.canceled_date, s.arrival_date)           AS cancellation_lead_days,
    s.market_segment_raw,
    s.distribution_channel_raw,
    s.agent_raw,
    s.company_raw,
    COALESCE(m.business_source, 'UNKNOWN')                  AS business_source,
    s.reserved_room_type,
    s.assigned_room_type,
    s.adults,
    s.children,
    s.babies,
    s.adr,
    s.currency,
    COALESCE(s.room_revenue_observed,
             s.adr * days_between(s.arrival_date, s.departure_date)) AS room_revenue,
    CASE WHEN s.room_revenue_observed IS NOT NULL THEN 'OBSERVED' ELSE 'ADR_DERIVED' END
                                                            AS room_revenue_basis,
    s.deposit_type_raw,
    s.customer_type_raw,
    CASE WHEN days_between(s.arrival_date, s.departure_date) = 0 THEN 1 ELSE 0 END
                                                            AS is_zero_night,
    CASE WHEN s.arrival_date > c.as_of_date THEN 1 ELSE 0 END AS is_future_arrival
FROM stg_reservation s
CROSS JOIN run_context c
LEFT JOIN dim_source_mapping m
       ON m.source_system = s.source_system
      AND m.market_segment_raw = s.market_segment_raw
WHERE s.record_type <> 'GROUP_MASTER';
