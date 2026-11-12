# Canonical schema v0.1

Two fact tables and two small dimensions. Every analysis reads these and never
the source files, so nothing downstream knows which PMS the data came from.

```
source file -> adapter -> stg_reservation -> fact_reservation -> fact_stay_night -> marts
```

An adapter's only job is to produce `stg_reservation`. Everything after that is
shared SQL.

## Provenance vocabulary

| Value | Meaning |
|---|---|
| `OBSERVED` | Recorded in the source |
| `DERIVED` | Calculated deterministically from source fields |
| `RECONSTRUCTED` | A historical state estimated from incomplete records |
| `SIMULATED` | Generated from stated assumptions |
| `UNAVAILABLE` | The source does not have it |

## `fact_reservation`

Grain: one row per individual room booking. A booking for three rooms is three
rows. Group master records are not rows here (they stay in `stg_reservation`).

| Column | Type | Null | Definition |
|---|---|---|---|
| `booking_id` | text | no | Primary key. Built by the adapter; unique across sources |
| `source_system` | text | no | Which adapter produced the row |
| `source_row_number` | integer | no | Row position in the source file, for traceability |
| `source_reservation_id` | text | yes | The PMS's own reservation number, if it has one |
| `property_code` | text | no | Joins to `dim_property` |
| `record_type` | text | no | `INDIVIDUAL_ROOM`, `GROUP_ROOM`, `UNKNOWN` (`GROUP_MASTER` exists only in staging) |
| `group_id` | text | yes | Links group pickup rooms to their group |
| `booking_date` | date | yes | Date the booking was created |
| `booking_date_basis` | text | no | Provenance of `booking_date` |
| `arrival_date`, `departure_date` | date | no | Scheduled stay |
| `los_nights` | integer | no | `departure_date - arrival_date` |
| `booking_lead_days` | integer | yes | `arrival_date - booking_date` |
| `reservation_status` | text | no | `RESERVED`, `IN_HOUSE`, `CHECKED_OUT`, `NO_SHOW`, `CANCELED` |
| `reservation_status_raw` | text | yes | The source's own status value, unchanged |
| `status_date` | date | yes | Date of the most recent status, if the source gives one |
| `is_canceled` | 0/1 | no | Derived: 1 only when status is `CANCELED`. No-shows are 0 |
| `canceled_date` | date | yes | Filled only for `CANCELED` |
| `canceled_at` | timestamp | yes | Filled only when the source has a real timestamp |
| `cancellation_date_basis` | text | no | Provenance of `canceled_date` |
| `cancellation_lead_days` | integer | yes | `arrival_date - canceled_date` |
| `market_segment_raw`, `distribution_channel_raw`, `agent_raw`, `company_raw` | text | yes | Source values, unchanged |
| `business_source` | text | no | Standardized source of business via `dim_source_mapping`; `UNKNOWN` if unmapped |
| `reserved_room_type`, `assigned_room_type` | text | yes | |
| `adults`, `children`, `babies` | integer | yes | |
| `adr` | decimal | yes | Average rate per night as reported for the booking |
| `currency` | text | yes | |
| `room_revenue` | decimal | yes | Observed room revenue if the source has it, otherwise `adr * los_nights` |
| `room_revenue_basis` | text | no | `OBSERVED` or `ADR_DERIVED` |
| `deposit_type_raw`, `customer_type_raw` | text | yes | Source values, where they exist |
| `is_zero_night` | 0/1 | no | Arrival and departure on the same date |
| `is_future_arrival` | 0/1 | no | Arrival after the run's as-of date |

Status rules:

- The five statuses are the whole vocabulary. A PMS that codes status as 1 to 5
  (reserved, in-house, checked-out, no-show, canceled) maps one to one.
- `is_canceled` is always derived from status. A source's own canceled flag is
  never trusted directly (the public dataset's flag also counts no-shows).
- A no-show has no `canceled_date` unless the source records a cancellation event.
- Dates are never promoted to timestamps.

Not in the schema on purpose: guest history (repeat guest, prior cancellations),
parking, special requests. A PMS without a CRM link cannot supply them reliably.
An adapter may keep such fields in its own `ext_<source>_reservation` side
table; no shared SQL may read it.

## `fact_stay_night`

Grain: one scheduled room-night per booking. A row means the night was booked,
not that the room was occupied. Canceled and no-show bookings keep their nights.
Zero-night bookings have none.

| Column | Type | Definition |
|---|---|---|
| `stay_night_id` | text | Primary key: `booking_id` plus night number |
| `booking_id` | text | Foreign key to `fact_reservation` |
| `property_code` | text | |
| `stay_date` | date | The night |
| `night_index` | integer | 1 for the arrival night |
| `los_nights` | integer | Length of the parent stay |
| `reserved_room_type`, `assigned_room_type` | text | |
| `reservation_status`, `business_source` | text | Copied from the parent for convenience |
| `booking_date`, `canceled_date` | date | Copied from the parent |
| `room_nights` | integer | Always 1 |
| `allocated_room_revenue` | decimal | Parent `room_revenue / los_nights` |
| `nightly_rate_basis` | text | `ADR_DERIVED_ALLOCATION` or `EVEN_SPLIT_OF_OBSERVED`. Neither is a real nightly rate |

Four quantities that must not be mixed up:

1. Scheduled room-nights: all rows.
2. Stayed room-nights: rows with status `CHECKED_OUT`.
3. Room-nights on the books at a past date: rows booked by then and not yet canceled.
   Reconstructed unless the source has event history.
4. Occupied rooms: not in this schema; needs in-house data and capacity.

## `dim_property`

`source_system, property_code, property_name, property_type, country,
capacity_rooms, capacity_basis`. Capacity is empty with basis `UNAVAILABLE`
when the source does not provide it. Occupancy and RevPAR need it.

## `dim_source_mapping`

`source_system, market_segment_raw, business_source, mapping_version, note`.
A CSV you edit in Excel. Standard values: `OTA`, `WHOLESALE`, `DIRECT`,
`CORPORATE`, `GROUP`, `COMP`, `OTHER`, `UNKNOWN`.

## Run context and manifest

Each run records the source system, the source file's SHA-256, and an
`as_of_date`. For a historical file that is the latest date in the data; for a
live PMS extract it is the extract date, and stay nights after it are future
business on the books. `manifest.json` carries these plus row counts, the
adapter version and the source's known limitations.

## Deferred tables

Not built. Each would attach without changing the tables above.

| Table | Would hold | Joins on |
|---|---|---|
| `fact_capacity_calendar` | Rooms available and restrictions per property, room type, date | `property_code`, `stay_date` |
| `fact_reservation_event` | Dated changes to a booking (dates, rate, room type, status) | `booking_id` |
| `fact_otb_snapshot` | True on-the-books positions captured on each snapshot date | `property_code`, `stay_date`, snapshot date |
| `fact_group_block_night` | Rooms blocked, picked up and released per group and date | `group_id`, `stay_date` |
| `fact_reservation_room` | Room-level rows, if a PMS cannot be expressed as one row per room | `booking_id` |
