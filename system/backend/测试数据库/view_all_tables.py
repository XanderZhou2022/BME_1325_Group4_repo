from __future__ import annotations

import argparse
import json
import os

import psycopg
from psycopg.rows import dict_row


DB_DSN = os.getenv("ICU_PG_DSN", "dbname=icu_agent user=zhou host=localhost port=5432")

TABLES = [
    "patients",
    "beds",
    "admissions",
    "events",
    "vital_sign_events",
    "lab_events",
    "intervention_events",
    "patient_state_current",
    "patient_state_snapshots",
    "agent_outputs",
    "agent_events",
    "agent_consumption_cursor",
    "agent_registry",
    "orchestrator_runs",
    "risk_assessments",
    "alerts",
    "audit_logs",
]


def pretty(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, default=str, indent=2)


def view_tables(limit: int) -> None:
    with psycopg.connect(DB_DSN, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            for table in TABLES:
                cur.execute(f"SELECT COUNT(*) AS n FROM {table};")
                total = cur.fetchone()["n"]

                print(f"\n{'=' * 20} {table} {'=' * 20}")
                print(f"total rows: {total}")

                if total == 0:
                    print("(empty)")
                    continue

                cur.execute(f"SELECT * FROM {table} ORDER BY 1 LIMIT %s;", (limit,))
                rows = cur.fetchall()
                for i, row in enumerate(rows, start=1):
                    print(f"\n[{table}] row {i}")
                    print(pretty(row))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="View all ICU core tables with sample rows."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="How many rows to show per table (default: 5)",
    )
    args = parser.parse_args()

    if args.limit <= 0:
        raise SystemExit("--limit must be > 0")

    view_tables(args.limit)


if __name__ == "__main__":
    main()

