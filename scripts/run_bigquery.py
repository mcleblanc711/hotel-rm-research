# /// script
# requires-python = ">=3.11"
# dependencies = ["google-cloud-bigquery==3.47.0", "sqlglot==30.31.0", "duckdb"]
# ///
"""Run the canonical pipeline in BigQuery and check it against the DuckDB run.

The same SQL files as run_pipeline.py, sent to BigQuery one job per file.
The SQL in sql/ is written in DuckDB's dialect; sqlglot translates it to
GoogleSQL, and sql/dialect/bigquery.sql supplies the date helpers.

    uv run scripts/run_bigquery.py --source antonio --translate-only   # no GCP needed
    uv run scripts/run_bigquery.py --source antonio --project MY_PROJECT
    uv run scripts/run_bigquery.py --source synthetic --project MY_PROJECT

Only the public dataset and the synthetic export are allowed here: this script
uploads data to Google Cloud (see "Data handling" in the README).

Writes to out/bigquery/<source>/:
    sql/*.sql               the exact GoogleSQL sent to BigQuery, for review
    qa_report.csv           QA results as BigQuery computed them
    engine_comparison.csv   per-column aggregates, DuckDB vs BigQuery
    run_log.json            job ids, bytes processed and bytes billed per step
"""
import argparse
import csv
import hashlib
import json
import os
import sys

import sqlglot
from sqlglot import exp

from pipeline_config import (
    AS_OF_FROM_STAGING_SQL, FAR_FUTURE, OUTPUT_TABLES, QA_REPORT_FETCH_SQL, ROOT,
    SEEDS, SOURCES, print_qa, qa_report_sql, run_context_sql, sql_steps,
)

ALLOWED_SOURCES = {"antonio", "synthetic"}  # public or made-up data only
DIALECT_FILE = ROOT / "sql/dialect/bigquery.sql"
MAX_BYTES_BILLED = 1 * 1024**3  # per job; the whole run bills well under this


# ---------------------------------------------------------------- translation

def _decimal_cast(node):
    """CAST(x AS DECIMAL(p, s)) -> ROUND(CAST(x AS NUMERIC), s).

    BigQuery only allows NUMERIC(p, s) on columns and script variables, so
    sqlglot drops (p, s) from a CAST and the rounding silently disappears.
    DuckDB rounds half away from zero when casting to DECIMAL, and so does
    ROUND on a NUMERIC in BigQuery, so the results match.
    """
    if isinstance(node, exp.Cast) and node.to.is_type(exp.DType.DECIMAL) and node.to.expressions:
        params = [p.this for p in node.to.expressions]
        scale = params[1] if len(params) > 1 else exp.Literal.number(0)
        plain = exp.Cast(this=node.this, to=exp.DataType.build("DECIMAL"))
        return exp.func("ROUND", plain, scale)
    return node


def to_bigquery(duckdb_sql):
    statements = [s for s in sqlglot.parse(duckdb_sql, read="duckdb") if s is not None]
    out = [s.transform(_decimal_cast).sql(dialect="bigquery", pretty=True) for s in statements]
    return ";\n\n".join(out) + ";\n"


def function_prelude():
    """The CREATE TEMP FUNCTION statements of the dialect file, for every job."""
    stmts = sqlglot.parse(DIALECT_FILE.read_text(), read="bigquery")
    funcs = [s.sql(dialect="bigquery", comments=False) for s in stmts
             if isinstance(s, exp.Create) and s.kind == "FUNCTION"]
    if not funcs:
        sys.exit(f"no CREATE TEMP FUNCTION statements found in {DIALECT_FILE}")
    return ";\n".join(funcs) + ";\n\n"


# ------------------------------------------------------------- comparison SQL

NUMERIC_TYPES = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "DECIMAL", "DOUBLE", "FLOAT")


def profile_sql(table, columns):
    """One-row aggregate profile of a table, written in DuckDB SQL.

    Numeric columns: non-null count and sum. Other columns: non-null count and
    distinct count. Dates also get min and max (as text).
    """
    exprs, labels = ["COUNT(*)"], [("*", "rows")]
    for name, typ in columns:
        q = f'"{name}"'
        exprs.append(f"COUNT({q})")
        labels.append((name, "non_null"))
        if typ.startswith(NUMERIC_TYPES):
            exprs.append(f"SUM(CAST({q} AS DOUBLE))")
            labels.append((name, "sum"))
        else:
            exprs.append(f"COUNT(DISTINCT {q})")
            labels.append((name, "distinct"))
        if typ == "DATE":
            exprs.append(f"CAST(MIN({q}) AS VARCHAR)")
            labels.append((name, "min"))
            exprs.append(f"CAST(MAX({q}) AS VARCHAR)")
            labels.append((name, "max"))
    select = ", ".join(f"{e} AS c{i}" for i, e in enumerate(exprs))
    return f"SELECT {select} FROM {table}", labels


def values_match(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        a, b = float(a), float(b)
        return abs(a - b) <= max(1e-6, 1e-9 * max(abs(a), abs(b)))
    return str(a) == str(b)


def compare_engines(bq_query, source, out):
    import duckdb

    db_file = ROOT / "out" / source / "canonical.duckdb"
    if not db_file.exists():
        print(f"\nNo DuckDB run found at {db_file.relative_to(ROOT)}; skipping comparison.")
        print(f"Run: uv run --with duckdb scripts/run_pipeline.py --source {source}")
        return None
    con = duckdb.connect(str(db_file), read_only=True)
    rows, mismatches = [], 0
    for table in OUTPUT_TABLES:
        cols = [(r[0], r[1]) for r in con.execute(f"DESCRIBE {table}").fetchall()]
        sql, labels = profile_sql(table, cols)
        local = con.execute(sql).fetchone()
        remote = list(bq_query(to_bigquery(sql)))[0]
        for i, (col, metric) in enumerate(labels):
            ok = values_match(local[i], remote[f"c{i}"])
            mismatches += not ok
            rows.append([table, col, metric, local[i], remote[f"c{i}"], int(ok)])
    with open(out / "engine_comparison.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["table", "column", "metric", "duckdb", "bigquery", "match"])
        w.writerows(rows)
    print(f"\nEngine comparison: {len(rows)} aggregates over {len(OUTPUT_TABLES)} tables, "
          f"{mismatches} mismatch(es). Details: {(out / 'engine_comparison.csv').relative_to(ROOT)}")
    for r in rows:
        if not r[5]:
            print(f"  MISMATCH {r[0]}.{r[1]} {r[2]}: duckdb={r[3]} bigquery={r[4]}")
    return mismatches


# ------------------------------------------------------------------- BigQuery

def read_csv_rows(path, with_row_number):
    """Rows as dicts with every value as text and empty fields as NULL,
    matching DuckDB's read_csv(all_varchar=true). Row numbers follow file order."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        rows = []
        for i, rec in enumerate(reader, start=1):
            row = {k: (v if v != "" else None) for k, v in rec.items()}
            if with_row_number:
                row = {"source_row_number": i, **row}
            rows.append(row)
    return header, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", choices=sorted(ALLOWED_SOURCES), default="antonio")
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                    help="GCP project id (or set GOOGLE_CLOUD_PROJECT)")
    ap.add_argument("--dataset", help="default: hotel_rm_<source>")
    ap.add_argument("--location", default="US")
    ap.add_argument("--translate-only", action="store_true",
                    help="write the translated SQL to out/ and stop; needs no GCP account")
    args = ap.parse_args()
    cfg = SOURCES[args.source]
    dataset = args.dataset or f"hotel_rm_{args.source}"

    out = ROOT / "out" / "bigquery" / args.source
    (out / "sql").mkdir(parents=True, exist_ok=True)

    src = ROOT / cfg["file"]
    fingerprint = hashlib.sha256(src.read_bytes()).hexdigest()
    prelude = function_prelude()
    files = [cfg["adapter"], *sql_steps(cfg)]
    translated = {f: to_bigquery((ROOT / f).read_text()) for f in files}
    for i, f in enumerate(files, start=1):
        name = f"{i:02d}_{f.rsplit('/', 1)[-1]}"
        (out / "sql" / name).write_text(f"-- Translated from {f} by scripts/run_bigquery.py\n\n"
                                        + prelude + translated[f])
    print(f"Wrote {len(files)} translated SQL files to {(out / 'sql').relative_to(ROOT)}/")
    if args.translate_only:
        return
    if not args.project:
        sys.exit("--project is required (or set GOOGLE_CLOUD_PROJECT)")

    from google.api_core.exceptions import GoogleAPICallError
    from google.auth.exceptions import DefaultCredentialsError
    from google.cloud import bigquery

    try:
        client = bigquery.Client(project=args.project, location=args.location)
    except DefaultCredentialsError:
        sys.exit("No Google credentials found. Run: gcloud auth application-default login")

    ds = bigquery.Dataset(f"{args.project}.{dataset}")
    ds.location = args.location
    client.create_dataset(ds, exists_ok=True)
    ds_ref = bigquery.DatasetReference(args.project, dataset)
    log = []

    def run(label, sql):
        job_config = bigquery.QueryJobConfig(default_dataset=ds_ref,
                                             maximum_bytes_billed=MAX_BYTES_BILLED)
        job = client.query(sql, job_config=job_config)
        try:
            result = job.result()
        except GoogleAPICallError as e:
            sys.exit(f"\nBigQuery failed on {label} (job {job.job_id}):\n{e}")
        log.append({"step": label, "job_id": job.job_id,
                    "bytes_processed": job.total_bytes_processed or 0,
                    "bytes_billed": job.total_bytes_billed or 0})
        print(f"  {label:45} {(job.total_bytes_billed or 0) / 1e6:9.1f} MB billed")
        return result

    def load(table, header, rows, int_columns=()):
        schema = [bigquery.SchemaField(c, "INT64" if c in int_columns else "STRING") for c in header]
        job_config = bigquery.LoadJobConfig(
            schema=schema, write_disposition="WRITE_TRUNCATE",
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON)
        client.load_table_from_json(rows, ds_ref.table(table), job_config=job_config).result()
        print(f"  load {table:40} {len(rows):9,} rows")

    print(f"\nBigQuery: {args.project}.{dataset} ({args.location})")
    header, rows = read_csv_rows(src, with_row_number=True)
    load("raw_source", ["source_row_number", *header], rows, int_columns={"source_row_number"})
    for seed in SEEDS:
        header, rows = read_csv_rows(ROOT / "data" / "seeds" / f"{seed}.csv", with_row_number=False)
        load(seed, header, rows)

    run("sql/dialect/bigquery.sql", DIALECT_FILE.read_text())
    run("run_context", run_context_sql(cfg["source_system"], fingerprint, cfg["as_of"] or FAR_FUTURE))
    run(cfg["adapter"], prelude + translated[cfg["adapter"]])
    if cfg["as_of"] is None:
        as_of = list(run("as_of", AS_OF_FROM_STAGING_SQL))[0][0]
        run("run_context", run_context_sql(cfg["source_system"], fingerprint, as_of))
    for f in sql_steps(cfg):
        run(f, prelude + translated[f])
    run("qa_report", to_bigquery(qa_report_sql(cfg)))

    qa = [tuple(r.values()) for r in run("fetch qa_report", QA_REPORT_FETCH_SQL)]
    fatal = print_qa(qa, f"{args.source}, BigQuery")
    with open(out / "qa_report.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["check_name", "severity", "observed", "expected", "passed", "description"])
        w.writerows(qa)

    mismatches = compare_engines(lambda sql: run("compare", sql), args.source, out)

    billed = sum(s["bytes_billed"] for s in log)
    (out / "run_log.json").write_text(json.dumps(
        {"project": args.project, "dataset": dataset, "location": args.location,
         "total_bytes_billed": billed, "steps": log}, indent=2) + "\n")
    print(f"\nTotal billed: {billed / 1e6:.1f} MB across {len(log)} jobs "
          f"(free tier: 1 TiB of queries a month).")
    if fatal or mismatches:
        sys.exit(1)


if __name__ == "__main__":
    main()
