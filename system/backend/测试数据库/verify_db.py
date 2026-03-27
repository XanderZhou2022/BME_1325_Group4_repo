from __future__ import annotations

import sys

import psycopg


DB_DSN = "dbname=icu_agent user=zhou host=localhost port=5432"

REQUIRED_TABLES = [
    "patients",
    "beds",
    "admissions",
    "events",
    "vital_sign_events",
    "lab_events",
    "intervention_events",
    "patient_state_current",
    "patient_state_snapshots",
    "risk_assessments",
    "alerts",
    "audit_logs",
]

MIN_COUNTS = {
    "patients": 3,
    "beds": 3,
    "admissions": 3,
    "vital_sign_events": 3,
    "lab_events": 3,
    "intervention_events": 3,
    "risk_assessments": 1,
    "alerts": 1,
    "audit_logs": 1,
}

REQUIRED_SCENARIOS = {
    "sepsis_progressive": "shock_risk",
    "resp_failure_worsening": "resp_failure_risk",
    "fluid_nonresponsive": "poor_fluid_response",
}


def check_tables_exist(cur: psycopg.Cursor) -> tuple[bool, list[str]]:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = ANY(%s)
        ORDER BY table_name;
        """,
        (REQUIRED_TABLES,),
    )
    existing = {row[0] for row in cur.fetchall()}
    missing = [t for t in REQUIRED_TABLES if t not in existing]
    return (len(missing) == 0, missing)


def check_min_counts(cur: psycopg.Cursor) -> tuple[bool, dict[str, int], list[str]]:
    counts: dict[str, int] = {}
    failed: list[str] = []
    for table in REQUIRED_TABLES:
        cur.execute(f"SELECT COUNT(*) FROM {table};")
        n = int(cur.fetchone()[0])
        counts[table] = n
        if table in MIN_COUNTS and n < MIN_COUNTS[table]:
            failed.append(f"{table}: {n} < {MIN_COUNTS[table]}")
    return (len(failed) == 0, counts, failed)


def check_scenarios(cur: psycopg.Cursor) -> tuple[bool, list[str], list[tuple[str, str, str, str]]]:
    cur.execute(
        """
        SELECT a.scenario_tag, a.admission_id, COALESCE(r.risk_type, ''), COALESCE(al.alert_type, '')
        FROM admissions a
        LEFT JOIN risk_assessments r ON r.admission_id = a.admission_id
        LEFT JOIN alerts al ON al.admission_id = a.admission_id
        WHERE a.scenario_tag = ANY(%s)
        ORDER BY a.scenario_tag, a.admission_id;
        """,
        (list(REQUIRED_SCENARIOS.keys()),),
    )
    rows = cur.fetchall()

    seen: dict[str, tuple[str, str, str, str]] = {}
    for row in rows:
        scenario = row[0]
        seen[scenario] = row

    failed: list[str] = []
    for scenario, expected_alert in REQUIRED_SCENARIOS.items():
        if scenario not in seen:
            failed.append(f"{scenario}: missing admission")
            continue
        _, admission_id, risk_type, alert_type = seen[scenario]
        if not risk_type:
            failed.append(f"{scenario}: no risk_assessments (admission={admission_id})")
        if alert_type != expected_alert:
            failed.append(
                f"{scenario}: alert_type='{alert_type}' expected='{expected_alert}' (admission={admission_id})"
            )

    return (len(failed) == 0, failed, rows)


def main() -> int:
    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                tables_ok, missing_tables = check_tables_exist(cur)
                counts_ok, counts, count_failures = check_min_counts(cur)
                scenarios_ok, scenario_failures, scenario_rows = check_scenarios(cur)
    except Exception as exc:
        print(f"[ERROR] Database connection/query failed: {exc}")
        return 2

    print("== ICU DB Verification ==")
    print(f"[{'PASS' if tables_ok else 'FAIL'}] required tables")
    if not tables_ok:
        for item in missing_tables:
            print(f"  - missing: {item}")

    print(f"[{'PASS' if counts_ok else 'FAIL'}] minimum row counts")
    for table in REQUIRED_TABLES:
        threshold = MIN_COUNTS.get(table, 0)
        mark = "OK" if counts[table] >= threshold else "LOW"
        print(f"  - {table}: {counts[table]} (min {threshold}) [{mark}]")
    if not counts_ok:
        for item in count_failures:
            print(f"  - issue: {item}")

    print(f"[{'PASS' if scenarios_ok else 'FAIL'}] scenario linkage checks")
    for scenario_tag, admission_id, risk_type, alert_type in scenario_rows:
        print(
            f"  - {scenario_tag}: admission={admission_id}, risk={risk_type or 'N/A'}, alert={alert_type or 'N/A'}"
        )
    if not scenarios_ok:
        for item in scenario_failures:
            print(f"  - issue: {item}")

    all_ok = tables_ok and counts_ok and scenarios_ok
    print(f"\nFinal: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
