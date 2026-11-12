# QA contract v0.1

Three kinds of checks. SQL lives in `sql/qa/`; results land in `qa_report.csv`.

## Structural (FATAL: the run fails)

| Check | Rule |
|---|---|
| `booking_id_unique` | No duplicate booking IDs |
| `source_rows_reconcile` | Source rows = reservations + staged group masters. Nothing dropped |
| `stay_nights_equal_sum_los` | Stay-night rows = sum of scheduled nights |
| `stay_night_orphans` | Every stay-night has a parent booking |
| `stay_date_outside_interval` | Every stay date is inside its booking's dates |
| `zero_night_bookings_have_no_nights` | Zero-night bookings produce no stay-nights |
| `negative_los` | No departure before arrival |
| `allocated_revenue_reconciles` | Nightly allocations sum to booking room revenue |
| `unknown_status` | Every status is one of the five canonical values |
| `group_master_in_fact` | No group master in `fact_reservation` |
| `canceled_without_status` | A cancellation date only on canceled bookings |

## Semantic (WARN: counted, reviewed, kept)

Negative or zero ADR, zero-night bookings, stays over 30 nights, zero or missing
guest counts, booking after arrival, cancellation after arrival or before
booking, canceled without a date, unmapped segments, and identical-looking rows.

Identical-looking rows are never removed. Without a real reservation number
there is no way to tell a duplicate from two matching bookings.

No row is deleted or altered by QA. An analysis that wants to exclude flagged
rows does so in its own query and says so.

## Source-specific

`sql/qa/antonio_profile.sql` tests the public dataset against figures quoted in
earlier notes. Current result: all agree (119,390 bookings; 79,330 City and
40,060 Resort; 75,166 checked-out, 43,017 canceled, 1,207 no-show; 409,257
scheduled room-nights, 255,040 on checked-out bookings; 715 zero-night; 1,959
zero ADR; 881 canceled on the arrival date).

One figure differs by definition: the notes counted 31,994 rows identical to an
earlier row across all 32 source columns; `identical_looking_rows` reports
35,949 because it compares only the canonical columns.

## Analytical rules (enforced by labels, not code)

- No occupancy % or RevPAR without capacity. Assumed capacity is labeled `SIMULATED`.
- Booking curves from sources without event history are labeled reconstructed.
- Final status is not used as a predictor at a date before it was known.
- Allocated nightly revenue is not presented as a rate schedule.
- Revenue on canceled bookings is not presented as realized.
