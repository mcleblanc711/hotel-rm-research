# /// script
# requires-python = ">=3.11"
# dependencies = ["google-cloud-bigquery==3.47.0", "sqlglot==30.31.0", "duckdb"]
# ///
"""Train the BigQuery ML forecasts and build the public dashboard tables.

Run after run_bigquery.py (which builds fc_dataset and the pickup models):

    uv run scripts/run_bigquery.py --source antonio --project MY_PROJECT
    uv run scripts/bigquery_forecast_dashboard.py --project MY_PROJECT

Steps, all in the source dataset unless noted:
  1. sql/bigquery_ml/linear_pickup.sql   LINEAR_REG model + fc_forecast_linear
  2. sql/bigquery_ml/arima_plus.sql      ARIMA_PLUS model + fc_forecast_arima
  3. fc_forecast = all five models; sql/forecast/accuracy.sql -> fc_accuracy
  4. sql/bigquery_ml/public_dashboard.sql -> tables in the public dataset
Prints the accuracy table, the ARIMA model's chosen settings, and a Looker
Studio link that opens a new report with the public tables connected.
Writes out/bigquery/<source>/forecast_accuracy.csv.
"""
import argparse
import csv
import os
import sys
import urllib.parse

from pipeline_config import (
    FC_ACCURACY_STEP, ROOT, SOURCES, fc_context_sql, fc_forecast_sql,
)
from run_bigquery import MAX_BYTES_BILLED, function_prelude, to_bigquery

ML_DIR = ROOT / "sql" / "bigquery_ml"
FORECAST_TABLES = ["fc_forecast_pickup", "fc_forecast_linear", "fc_forecast_arima"]
PUBLIC_TABLES = ["forecast_nightly", "forecast_accuracy", "booking_pace"]


def looker_studio_url(project, dataset, tables, report_name):
    """Linking API URL: a new report with one BigQuery data source per table."""
    params = [("c.mode", "edit"), ("r.reportName", report_name)]
    for i, table in enumerate(tables):
        a = f"ds.ds{i}"
        params += [(f"{a}.connector", "bigQuery"), (f"{a}.type", "TABLE"),
                   (f"{a}.projectId", project), (f"{a}.datasetId", dataset),
                   (f"{a}.tableId", table), (f"{a}.datasourceName", table)]
    return "https://lookerstudio.google.com/reporting/create?" + urllib.parse.urlencode(params)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    ap.add_argument("--source", choices=["antonio"], default="antonio")
    ap.add_argument("--dataset", help="source dataset, default: hotel_rm_<source>")
    ap.add_argument("--public-dataset", default="hotel_rm_public")
    ap.add_argument("--location", default="US")
    args = ap.parse_args()
    if not args.project:
        sys.exit("--project is required (or set GOOGLE_CLOUD_PROJECT)")
    cfg = SOURCES[args.source]
    fc = cfg["forecast"]
    dataset = args.dataset or f"hotel_rm_{args.source}"

    from google.api_core.exceptions import GoogleAPICallError
    from google.cloud import bigquery

    client = bigquery.Client(project=args.project, location=args.location)
    ds_ref = bigquery.DatasetReference(args.project, dataset)
    pub = bigquery.Dataset(f"{args.project}.{args.public_dataset}")
    pub.location = args.location
    pub.description = ("Public, pre-aggregated tables behind the Hotel RM Research dashboard. "
                       "Source: Hotel Booking Demand dataset (Antonio, Almeida & Nunes, 2019), CC BY 4.0.")
    client.create_dataset(pub, exists_ok=True)

    def run(label, sql):
        job = client.query(sql, job_config=bigquery.QueryJobConfig(
            default_dataset=ds_ref, maximum_bytes_billed=MAX_BYTES_BILLED))
        try:
            rows = list(job.result())
        except GoogleAPICallError as e:
            sys.exit(f"\nBigQuery failed on {label} (job {job.job_id}):\n{e}")
        print(f"  {label:45} {(job.total_bytes_billed or 0) / 1e6:9.1f} MB billed")
        return rows

    def ml_file(name):
        return ((ML_DIR / name).read_text()
                .replace("{{horizon_days}}", str(int(fc["horizon_days"])))
                .replace("{{public_dataset}}", args.public_dataset))

    print(f"BigQuery: {args.project}.{dataset} -> {args.public_dataset}")
    run("fc_context", fc_context_sql(fc))
    run("linear_pickup.sql", ml_file("linear_pickup.sql"))
    run("arima_plus.sql", ml_file("arima_plus.sql"))
    run("fc_forecast (5 models)", fc_forecast_sql(FORECAST_TABLES))
    run(FC_ACCURACY_STEP, function_prelude() + to_bigquery((ROOT / FC_ACCURACY_STEP).read_text()))
    run("public_dashboard.sql", ml_file("public_dashboard.sql"))

    acc = run("fetch accuracy", """
        SELECT model, property_code, horizon_bucket, n_nights, wape, mae, bias
        FROM fc_accuracy ORDER BY property_code, horizon_bucket, model""")
    out = ROOT / "out" / "bigquery" / args.source
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "forecast_accuracy.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "property_code", "horizon_bucket", "n_nights", "wape", "mae", "bias"])
        w.writerows([tuple(r.values()) for r in acc])

    print(f"\nForecast accuracy, both hotels (forecast made {fc['forecast_date']}; WAPE, lower is better)")
    buckets = sorted({r["horizon_bucket"] for r in acc if r["property_code"] == "ALL"})
    models = sorted({r["model"] for r in acc})
    print(f"{'model':24}" + "".join(f"{b:>9}" for b in buckets))
    for m in models:
        cells = {r["horizon_bucket"]: r["wape"] for r in acc if r["model"] == m and r["property_code"] == "ALL"}
        print(f"{m:24}" + "".join(f"{cells.get(b, float('nan')):9.3f}" for b in buckets))

    print("\nARIMA_PLUS settings chosen per series:")
    for r in run("arima evaluate", "SELECT * FROM ML.ARIMA_EVALUATE(MODEL fc_model_arima)"):
        r = dict(r)
        print(f"  {r['property_code']:7} ARIMA({r['non_seasonal_p']},{r['non_seasonal_d']},{r['non_seasonal_q']}) "
              f"seasonal={r['seasonal_periods']} holidays={r['has_holiday_effect']} "
              f"spikes/dips={r['has_spikes_and_dips']} step_changes={r['has_step_changes']}")

    print("\nOpen this link to start the Looker Studio report with the public tables connected:")
    print(looker_studio_url(args.project, args.public_dataset, PUBLIC_TABLES, "Hotel RM: pace and pickup forecasting"))


if __name__ == "__main__":
    main()
