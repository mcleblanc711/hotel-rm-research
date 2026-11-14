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
import sys

import duckdb
from pipeline_config import (
    AS_OF_FROM_STAGING_SQL, FAR_FUTURE, OUTPUT_TABLES, QA_REPORT_FETCH_SQL, ROOT,
    SCHEMA_VERSION, SEEDS, SOURCES, print_qa, qa_report_sql, run_context_sql, sql_steps,
)


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
    for seed in SEEDS:
        con.execute(
            f"CREATE TABLE {seed} AS SELECT * FROM read_csv(?, header=true, all_varchar=true)",
            [str(ROOT / "data" / "seeds" / f"{seed}.csv")],
        )

    con.execute(run_context_sql(cfg["source_system"], fingerprint, cfg["as_of"] or FAR_FUTURE))
    run_sql(con, cfg["adapter"])
    if cfg["as_of"] is None:
        as_of = con.execute(AS_OF_FROM_STAGING_SQL).fetchone()[0]
        con.execute(run_context_sql(cfg["source_system"], fingerprint, as_of))

    for f in sql_steps(cfg):
        run_sql(con, f)

    con.execute(qa_report_sql(cfg))
    fatal = print_qa(con.execute(QA_REPORT_FETCH_SQL).fetchall(), args.source)

    tables = OUTPUT_TABLES
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
