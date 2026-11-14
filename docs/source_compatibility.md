# Source compatibility

How each source fills the staging contract (`stg_reservation`).

| Canonical field | Public dataset (Antonio et al.) | Synthetic PMS export | A real PMS export |
|---|---|---|---|
| `booking_id` | Surrogate: file fingerprint + row number | Property + reservation number + room sequence | To confirm |
| `source_reservation_id` | Unavailable | `ResNo` | To confirm |
| `property_code` | `hotel` | `PropCode` | To confirm |
| `record_type` | Always individual | From `RecType` and `GroupNo` | To confirm how group masters appear |
| `group_id` | Unavailable | `GroupNo` | To confirm |
| `booking_date` | Derived: arrival minus `lead_time` | Observed: `CreatedOn` | To confirm |
| `arrival_date` | Built from year, month name, day | `ArrDate` | To confirm |
| `departure_date` | Derived: arrival + weekend nights + week nights | `DepDate` | To confirm |
| `reservation_status` | `Check-Out`, `No-Show`, `Canceled` | Codes 1 to 5 | Codes 1 to 5 as described; confirm on a real extract |
| `status_date` | `reservation_status_date` | Unavailable | To confirm |
| `canceled_date` | Status date, for `Canceled` only | Observed: `CancelledOn` | To confirm |
| `canceled_at` | Unavailable (dates only) | Observed | To confirm |
| `market_segment_raw` | `market_segment` | `MktSeg` | To confirm |
| `distribution_channel_raw` | `distribution_channel` | Unavailable | To confirm |
| `agent_raw`, `company_raw` | Anonymized IDs | Unavailable | To confirm |
| Room types | Anonymized letters | Codes | To confirm |
| `adr` | `adr` (booking average) | `RateAmt` | To confirm |
| `room_revenue_observed` | Unavailable | `RoomRevTotal` | To confirm |
| Guest history, parking | Present; kept in `ext_antonio_reservation` only | Absent | Expected absent |
| Modification history | Unavailable (`booking_changes` is a count only) | Unavailable | To confirm |
| Capacity | Unavailable | Simulated in `dim_property` | To confirm |

The right-hand column is deliberately empty. Fill it from a real extract, on a
machine where that data is allowed to be, by copying
`sql/adapters/synthetic_pms_to_staging.sql` and changing the source column names.

## Writing an adapter for a private PMS

1. Put the export in `data/private/` (ignored by git).
2. Copy the synthetic adapter and map your columns.
3. Add your segment codes to `data/seeds/dim_source_mapping.csv` under a new `source_system`.
4. Add a source entry in `scripts/pipeline_config.py`, or run the SQL files in order in your own database.
5. Run the QA scripts. All structural checks must pass before any chart is trusted.

Things to check on the first real extract:

- Does one row mean one room? If a booking row can cover several rooms, split it
  in the adapter (one `booking_id` per room) rather than flattening it.
- How do group masters and room blocks appear? Masters must be staged as
  `GROUP_MASTER` so they add no room-nights.
- Are canceled reservations kept with their original dates?
- Is the rate field a booking average or a nightly amount?
