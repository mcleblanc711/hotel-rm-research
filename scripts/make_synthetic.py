"""Generate a small synthetic PMS-style export (no real data).

Deliberately shaped differently from the public dataset: its own column names,
numeric status codes 1-5, timestamps, a group master row, multi-room bookings,
future and in-house reservations, observed revenue, and no guest-history or
parking columns. Deterministic: re-running produces the same file.

    python3 scripts/make_synthetic.py
"""
import csv
import datetime as dt
import pathlib
import random

ROOT = pathlib.Path(__file__).resolve().parent.parent
AS_OF = dt.date(2026, 3, 15)
rng = random.Random(7)

SEGS = [("OTA-A", 0.30, 190), ("OTA-B", 0.15, 185), ("WHL", 0.12, 140), ("DIR-WEB", 0.20, 205),
        ("DIR-PH", 0.10, 210), ("CORP", 0.10, 165), ("COMP", 0.03, 0)]
ROOMS = ["KNG", "QQ", "STE"]
rows, res_no = [], 50000


def status_for(created, arr, dep, cancel_prob):
    """Return (status_code, cancelled_on) consistent with the as-of date."""
    if rng.random() < cancel_prob:
        last = min(arr, AS_OF)
        if last >= created:
            when = created + dt.timedelta(days=rng.randint(0, (last - created).days))
            ts = dt.datetime.combine(when, dt.time(rng.randint(7, 21), rng.randint(0, 59)))
            return 5, ts.isoformat(sep=" ")
    if arr > AS_OF:
        return 1, ""
    if dep > AS_OF:
        return 2, ""
    return (4 if rng.random() < 0.03 else 3), ""


def add(prop, group, rec, seq, created, arr, nights, seg, rate, cancel_prob=0.2, rno=None):
    dep = arr + dt.timedelta(days=nights)
    if rec == "M":
        st, cx = (1 if arr > AS_OF else 3), ""
    else:
        st, cx = status_for(created.date(), arr, dep, cancel_prob)
    room = rng.choice(ROOMS)
    rows.append({
        "ResNo": rno, "RoomSeq": seq, "PropCode": prop, "GroupNo": group, "RecType": rec,
        "CreatedOn": created.isoformat(sep=" "), "ArrDate": arr.isoformat(), "DepDate": dep.isoformat(),
        "StatusCode": st, "CancelledOn": cx, "MktSeg": seg,
        "RoomTypeBooked": room, "RoomTypeAssigned": room if st in (2, 3) else "",
        "Adults": rng.randint(1, 2), "Kids": rng.choice([0, 0, 0, 1, 2]),
        "RateAmt": f"{rate:.2f}", "RoomRevTotal": f"{rate * nights:.2f}", "Currency": "CAD",
    })


def created_before(arr, max_lead):
    d = arr - dt.timedelta(days=rng.randint(0, max_lead))
    return dt.datetime.combine(d, dt.time(rng.randint(6, 22), rng.randint(0, 59)))


for _ in range(190):
    res_no += 1
    prop = rng.choice(["LODGE", "LODGE", "INN"])
    arr = dt.date(2026, 1, 5) + dt.timedelta(days=rng.randint(0, 145))
    seg, _, base = rng.choices(SEGS, weights=[s[1] for s in SEGS])[0]
    rate = base * rng.uniform(0.85, 1.3) if base else 0
    nights = rng.choice([1, 1, 2, 2, 2, 3, 3, 4, 5, 7])
    created = created_before(arr, 120)
    n_rooms = 3 if rng.random() < 0.04 else 1  # a few multi-room bookings
    for seq in range(1, n_rooms + 1):
        add(prop, "", "R", seq, created, arr, nights, seg, rate, rno=res_no)

# One group: a master row (not a room) plus 14 picked-up rooms.
g_arr = dt.date(2026, 4, 16)
res_no += 1
add("LODGE", "G1001", "M", 1, dt.datetime(2025, 11, 3, 10, 15), g_arr, 3, "GRP", 0, rno=res_no)
for _ in range(14):
    res_no += 1
    add("LODGE", "G1001", "R", 1, created_before(g_arr, 90), g_arr, rng.choice([2, 3, 3]), "GRP", 155.0,
        cancel_prob=0.1, rno=res_no)

out = ROOT / "data" / "synthetic" / "pms_export.csv"
with out.open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(f"wrote {len(rows)} rows to {out.relative_to(ROOT)}")
