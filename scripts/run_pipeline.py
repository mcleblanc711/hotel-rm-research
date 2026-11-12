"""Thin runner: executes the SQL files in order with DuckDB and writes exports.

All transformation logic lives in sql/. This script only loads the raw file,
runs the scripts, and writes CSVs plus a manifest.

    uv run --with duckdb scripts/run_pipeline.py --source antonio
    uv run --with duckdb scripts/run_pipeline.py --source synthetic
"""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys

import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_VERSION = "0.1"

SOURCES = {
    "antonio": {
        "source_system": "ANTONIO",
        "file": "data/raw/hotel_bookings.csv",
        "adapter": "sql/adapters/antonio_to_staging.sql",
        "adapter_version": "1",
        "extra_qa": ["sql/qa/antonio_profile.sql"],
        "as_of": None,  # historical file: derived from the latest status date
        "limitations": [
            "No authentic reservation IDs; booking_id is a surrogate from row position.",
            "booking_date is derived as arrival_date minus lead_time.",
            "No modification history: booking curves are reconstructed from final state.",
            "ADR is reservation-level; nightly revenue is an even allocation.",
            "No verified capacity: occupancy and RevPAR are not computable without assumptions.",
        ],
    },
    "synthetic": {
        "source_system": "SYNTH",
        "file": "data/synthetic/pms_export.csv",
        "adapter": "sql/adapters/synthetic_pms_to_staging.sql",
        "adapter_version": "1",
        "extra_qa": [],
        "as_of": "2026-03-15",
        "limitations": ["Hand-made synthetic data used only to prove adapter portability."],
    },
}


def run_sql(con, rel_path):
    con.execute((ROOT / rel_path).read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=SOURCES, default="antonio")
    args = ap.parse_args()
    cfg = SOURCES[args.source]

    src = ROOT / cfg["file"]
    fingerprint = hashlib.sha256(src.read_bytes()).hexdigest()
    out = ROOT / "out" / args.source
    out.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    run_sql(con, "sql/dialect/duckdb.sql")

    # Raw load: every column as text, original row order preserved.
    con.execute(
        "CREATE TABLE raw_source AS SELECT row_number() OVER () AS source_row_number, * "
        "FROM read_csv(?, all_varchar=true, header=true, parallel=false)",
        [str(src)],
    )
    for seed in ("dim_source_mapping", "dim_property"):
        con.execute(
            f"CREATE TABLE {seed} AS SELECT * FROM read_csv(?, header=true, all_varchar=true)",
            [str(ROOT / "data" / "seeds" / f"{seed}.csv")],
        )

    con.execute(
        "CREATE TABLE run_context AS SELECT ? AS source_system, ? AS source_fingerprint, "
        "CAST(? AS DATE) AS as_of_date",
        [cfg["source_system"], fingerprint, cfg["as_of"] or "2999-12-31"],
    )
    run_sql(con, cfg["adapter"])
    if cfg["as_of"] is None:
        con.execute("UPDATE run_context SET as_of_date = (SELECT MAX(status_date) FROM stg_reservation)")

    for f in (
        "sql/canonical/fact_reservation.sql",
        "sql/canonical/fact_stay_night.sql",
        "sql/qa/structural.sql",
        "sql/qa/semantic.sql",
        *cfg["extra_qa"],
        "sql/marts/booking_curve.sql",
    ):
        run_sql(con, f)

    qa = con.execute(
        "SELECT check_name, severity, observed, expected, "
        "CASE WHEN expected IS NULL THEN NULL WHEN observed = expected THEN 1 ELSE 0 END AS passed, "
        "description FROM qa_results ORDER BY severity, check_name"
    ).fetchall()
    con.execute(
        "CREATE TABLE qa_report AS SELECT *, CASE WHEN expected IS NULL THEN NULL "
        "WHEN observed = expected THEN 1 ELSE 0 END AS passed FROM qa_results"
    )

    print(f"\nQA report ({args.source})")
    print(f"{'check':40} {'sev':6} {'observed':>12} {'expected':>12}  result")
    fatal = 0
    for name, sev, obs, exp, passed, _ in qa:
        result = "review" if passed is None else ("ok" if passed else "MISMATCH")
        if sev == "FATAL" and passed == 0:
            fatal += 1
        exp_s = "" if exp is None else f"{exp:,.0f}"
        print(f"{name:40} {sev:6} {obs:>12,.0f} {exp_s:>12}  {result}")

    tables = ["fact_reservation", "fact_stay_night", "dim_property", "dim_source_mapping",
              "mart_booking_curve", "mart_booking_curve_compact", "qa_report"]
    counts = {}
    for t in tables:
        con.execute(f"COPY {t} TO '{out / (t + '.csv')}' (HEADER, DELIMITER ',')")
        counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

    as_of = con.execute("SELECT as_of_date FROM run_context").fetchone()[0]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source_system": cfg["source_system"],
        "source_file": cfg["file"],
        "source_sha256": fingerprint,
        "adapter": cfg["adapter"],
        "adapter_version": cfg["adapter_version"],
        "as_of_date": str(as_of),
        "processed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "row_counts": counts,
        "fatal_qa_failures": fatal,
        "known_limitations": cfg["limitations"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    db_file = out / "canonical.duckdb"
    db_file.unlink(missing_ok=True)
    con.execute(f"ATTACH '{db_file}' AS disk")
    for t in tables + ["stg_reservation", "run_context"]:
        con.execute(f"CREATE OR REPLACE TABLE disk.{t} AS SELECT * FROM {t}")

    print(f"\nWrote {len(tables)} CSVs + manifest.json to {out.relative_to(ROOT)}/")
    if fatal:
        print(f"{fatal} FATAL QA check(s) failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
