# /// script
# requires-python = ">=3.11"
# dependencies = ["google-cloud-bigquery==3.47.0"]
# ///
"""Measure what partitioning and clustering do to bytes scanned in BigQuery.

Copies fact_stay_night (built by run_bigquery.py) into four layouts and runs
the same queries against each, with the query cache off:

    plain          no partitioning, no clustering
    part_month     PARTITION BY DATE_TRUNC(stay_date, MONTH)
    clust_date     CLUSTER BY stay_date, property_code, business_source
    part_clust     monthly partitions, CLUSTER BY property_code, business_source

Needs a billing-enabled project. The sandbox forces a 60-day partition
expiration counted from each partition's date, which empties date-partitioned
tables of 2015-2017 data (see docs/bigquery.md).

For every query it records the dry-run estimate (known before running) and
the bytes actually processed and billed (known only after).

    uv run scripts/bigquery_layout_benchmark.py --project MY_PROJECT [--source antonio]

Writes out/bigquery/<source>/layout_benchmark.csv. The bench_* tables are
left in the dataset for inspection.
"""
import argparse
import csv
import os
import sys

from pipeline_config import ROOT

LAYOUTS = {
    "plain": "",
    "part_month": "PARTITION BY DATE_TRUNC(stay_date, MONTH)",
    "clust_date": "CLUSTER BY stay_date, property_code, business_source",
    "part_clust": "PARTITION BY DATE_TRUNC(stay_date, MONTH) CLUSTER BY property_code, business_source",
}

# Questions an RM analyst actually asks of the stay-night fact. {t} is the table.
QUERIES = {
    "q1_one_month_one_hotel": (
        "Pace for one stay month at one property",
        """SELECT business_source, DATE_DIFF(stay_date, booking_date, DAY) AS days_out,
                  SUM(room_nights) AS rn
           FROM {t}
           WHERE stay_date BETWEEN '2016-08-01' AND '2016-08-31' AND property_code = 'CITY'
           GROUP BY 1, 2"""),
    "q1b_one_booking_month": (
        "Pickup: room-nights booked in one month (filters booking_date, not the partition column)",
        """SELECT stay_date, SUM(room_nights) AS rn
           FROM {t}
           WHERE booking_date BETWEEN '2016-08-01' AND '2016-08-31' AND property_code = 'CITY'
           GROUP BY 1"""),
    "q2_one_night_one_hotel": (
        "Every booking for one stay night at one property",
        """SELECT booking_id, booking_date, canceled_date, business_source
           FROM {t}
           WHERE stay_date = '2016-12-31' AND property_code = 'RESORT'"""),
    "q3_one_source_all_time": (
        "One source of business across all dates",
        """SELECT DATE_TRUNC(stay_date, MONTH) AS m, SUM(room_nights) AS rn
           FROM {t}
           WHERE business_source = 'GROUP'
           GROUP BY 1"""),
    "q4_full_table_total": (
        "Room-nights by property, no filter",
        "SELECT property_code, SUM(room_nights) AS rn FROM {t} GROUP BY 1"),
    "q5_select_star_limit": (
        "SELECT * ... LIMIT 10",
        "SELECT * FROM {t} LIMIT 10"),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    ap.add_argument("--source", choices=["antonio", "synthetic"], default="antonio")
    ap.add_argument("--dataset", help="default: hotel_rm_<source>")
    ap.add_argument("--location", default="US")
    args = ap.parse_args()
    if not args.project:
        sys.exit("--project is required (or set GOOGLE_CLOUD_PROJECT)")
    dataset = args.dataset or f"hotel_rm_{args.source}"

    from google.cloud import bigquery

    client = bigquery.Client(project=args.project, location=args.location)
    ds = f"{args.project}.{dataset}"
    cap = 1 * 1024**3

    print(f"Building layouts in {ds}")
    for name, clause in LAYOUTS.items():
        t = f"`{ds}.bench_{name}`"
        # CREATE OR REPLACE cannot change a table's partitioning, so drop first.
        client.query(f"DROP TABLE IF EXISTS {t}; "
                     f"CREATE TABLE {t} {clause} AS SELECT * FROM `{ds}.fact_stay_night`").result()
        meta = client.get_table(f"{ds}.bench_{name}")
        print(f"  bench_{name:12} {meta.num_rows:,} rows, {meta.num_bytes / 1e6:.1f} MB")

    rows = []
    for qid, (label, sql) in QUERIES.items():
        for name in LAYOUTS:
            q = sql.format(t=f"`{ds}.bench_{name}`")
            dry = client.query(q, job_config=bigquery.QueryJobConfig(
                dry_run=True, use_query_cache=False))
            job = client.query(q, job_config=bigquery.QueryJobConfig(
                use_query_cache=False, maximum_bytes_billed=cap))
            job.result()
            rows.append([qid, label, name, dry.total_bytes_processed,
                         job.total_bytes_processed, job.total_bytes_billed, job.slot_millis])

    out = ROOT / "out" / "bigquery" / args.source
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "layout_benchmark.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["query", "description", "layout", "dry_run_bytes", "bytes_processed",
                    "bytes_billed", "slot_ms"])
        w.writerows(rows)

    print(f"\n{'query':26} {'layout':11} {'estimate MB':>11} {'processed MB':>12} {'billed MB':>9}")
    for qid, _, name, est, proc, billed, _ in rows:
        print(f"{qid:26} {name:11} {est / 1e6:11.2f} {proc / 1e6:12.2f} {billed / 1e6:9.1f}")
    print(f"\nWrote {(out / 'layout_benchmark.csv').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
