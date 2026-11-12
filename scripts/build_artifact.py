"""Build the Booking Curve Explorer page from the canonical tables.

Packs fact_reservation into 10 bytes per booking, base64-encodes it, and
inlines it into artifact/booking_curve_explorer.template.html.

    uv run --with duckdb scripts/build_artifact.py

Public dataset only. Never point this at private data: the output is a
self-contained page meant to be published.
"""
import base64
import pathlib
import struct

import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOB = {"OTA": 0, "WHOLESALE": 1, "DIRECT": 2, "CORPORATE": 3, "GROUP": 4}  # everything else -> 5
STATUS = {"CHECKED_OUT": 0, "NO_SHOW": 1, "CANCELED": 2}

con = duckdb.connect(str(ROOT / "out" / "antonio" / "canonical.duckdb"), read_only=True)
assert con.execute("SELECT source_system FROM run_context").fetchone()[0] == "ANTONIO"
rows = con.execute(
    """
    SELECT property_code, reservation_status, business_source, los_nights,
           days_between(CAST('2015-07-01' AS DATE), arrival_date) AS arr,
           booking_lead_days, cancellation_lead_days, adr
    FROM fact_reservation ORDER BY source_row_number
    """
    .replace("days_between(CAST('2015-07-01' AS DATE), arrival_date)",
             "CAST(arrival_date - CAST('2015-07-01' AS DATE) AS INTEGER)")
).fetchall()

buf = bytearray()
for prop, status, sob, los, arr, lead, clead, adr in rows:
    b0 = (1 if prop == "RESORT" else 0) | (STATUS[status] << 1) | (SOB.get(sob, 5) << 3)
    adr10 = max(0, min(65535, round(float(adr) * 10)))
    buf += struct.pack("<BBHHHH", b0, los, arr, lead, 65535 if clead is None else clead, adr10)

template = (ROOT / "artifact" / "booking_curve_explorer.template.html").read_text()
html = template.replace("__DATA_B64__", base64.b64encode(bytes(buf)).decode()).replace(
    "__N_BOOKINGS__", str(len(rows))
)
out = ROOT / "out" / "artifact"
out.mkdir(parents=True, exist_ok=True)
(out / "booking-curve-explorer.html").write_text(html)
print(f"{len(rows):,} bookings, {len(buf):,} bytes packed, page {len(html) / 1e6:.2f} MB")
