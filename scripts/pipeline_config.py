"""What the pipeline runs, shared by every engine runner.

run_pipeline.py (DuckDB) and run_bigquery.py both read this module, so a source
or a SQL step is added once and every engine picks it up. Engine-specific code
stays in the runners and in sql/dialect/.
"""
import datetime as dt
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_VERSION = "0.1"

SOURCES = {
    "antonio": {
        "source_system": "ANTONIO",
        "file": "data/raw/hotel_bookings.csv",
        "adapter": "sql/adapters/antonio_to_staging.sql",
        "adapter_version": "1",
        # (sql file, the qa_* table it creates)
        "extra_qa": [("sql/qa/antonio_profile.sql", "qa_antonio_profile")],
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

SEEDS = ("dim_source_mapping", "dim_property")

# Tables every run publishes (CSV exports locally, compared across engines).
OUTPUT_TABLES = [
    "fact_reservation", "fact_stay_night", "dim_property", "dim_source_mapping",
    "mart_booking_curve", "mart_booking_curve_compact", "qa_report",
]

FAR_FUTURE = "2999-12-31"  # placeholder as_of until the adapter has run


def sql_steps(cfg):
    """SQL files to run after the adapter and the as_of resolution, in order."""
    return [
        "sql/canonical/fact_reservation.sql",
        "sql/canonical/fact_stay_night.sql",
        "sql/qa/structural.sql",
        "sql/qa/semantic.sql",
        *(f for f, _ in cfg["extra_qa"]),
        "sql/marts/booking_curve.sql",
    ]


def qa_tables(cfg):
    return ["qa_structural", "qa_semantic", *(t for _, t in cfg["extra_qa"])]


def run_context_sql(source_system, fingerprint, as_of):
    """CREATE run_context from literals. Inputs are checked, so inlining is safe."""
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", source_system):
        raise ValueError(f"bad source_system {source_system!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("fingerprint must be a sha256 hex digest")
    dt.date.fromisoformat(str(as_of))
    return (
        f"CREATE OR REPLACE TABLE run_context AS SELECT '{source_system}' AS source_system, "
        f"'{fingerprint}' AS source_fingerprint, CAST('{as_of}' AS DATE) AS as_of_date"
    )


AS_OF_FROM_STAGING_SQL = "SELECT MAX(status_date) FROM stg_reservation"


def qa_report_sql(cfg):
    """Union the per-file QA tables and add the passed flag."""
    union = " UNION ALL ".join(f"SELECT * FROM {t}" for t in qa_tables(cfg))
    return (
        f"CREATE OR REPLACE TABLE qa_report AS SELECT *, "
        f"CASE WHEN expected IS NULL THEN NULL WHEN observed = expected THEN 1 ELSE 0 END AS passed "
        f"FROM ({union}) q"
    )


QA_REPORT_FETCH_SQL = (
    "SELECT check_name, severity, observed, expected, passed, description "
    "FROM qa_report ORDER BY severity, check_name"
)


def print_qa(rows, label):
    """Print the QA table and return the number of failed FATAL checks."""
    print(f"\nQA report ({label})")
    print(f"{'check':40} {'sev':6} {'observed':>12} {'expected':>12}  result")
    fatal = 0
    for name, sev, obs, exp, passed, _ in rows:
        result = "review" if passed is None else ("ok" if passed else "MISMATCH")
        if sev == "FATAL" and passed == 0:
            fatal += 1
        exp_s = "" if exp is None else f"{exp:,.0f}"
        print(f"{name:40} {sev:6} {obs:>12,.0f} {exp_s:>12}  {result}")
    return fatal
