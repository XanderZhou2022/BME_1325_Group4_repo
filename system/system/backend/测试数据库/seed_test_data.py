from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import psycopg


DB_DSN = "dbname=icu_agent user=zhou host=localhost port=5432"


def j(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False)


def main() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)

    patients = [
        ("p1", "P001", "Zhang San", "male", 68, "1958-03-12", {"comorbidities": ["hypertension", "diabetes"], "allergies": ["penicillin"]}),
        ("p2", "P002", "Li Si", "female", 57, "1969-08-20", {"comorbidities": ["copd"], "allergies": []}),
        ("p3", "P003", "Wang Wu", "male", 72, "1954-01-09", {"comorbidities": ["ckd", "coronary_artery_disease"], "allergies": []}),
    ]

    beds = [
        ("b1", "ICU-01", "Room-A", "standard", "occupied", None),
        ("b2", "ICU-02", "Room-A", "standard", "occupied", None),
        ("b3", "ICU-03", "Room-B", "isolation", "occupied", "contact isolation"),
        ("b4", "ICU-04", "Room-B", "standard", "empty", None),
    ]

    admissions = [
        ("adm1", "p1", "b1", "ADM-001", now - timedelta(hours=26), None, "active", "septic shock", "ED transfer due to persistent hypotension", "critical", "ICU Team A", "sepsis_progressive"),
        ("adm2", "p2", "b2", "ADM-002", now - timedelta(hours=18), None, "active", "acute hypoxemic respiratory failure", "ward deterioration with increasing oxygen demand", "unstable", "ICU Team A", "resp_failure_worsening"),
        ("adm3", "p3", "b3", "ADM-003", now - timedelta(hours=40), None, "active", "post-op hemodynamic instability", "post-op monitoring with poor fluid response", "critical", "ICU Team B", "fluid_nonresponsive"),
    ]

    vital_sign_events = [
        ("vital1", "adm1", now - timedelta(hours=3), 122, 61, 92, 52, 28, 38.6, 90, 0.60, 63, 280, 7.29, 12),
        ("vital2", "adm1", now - timedelta(hours=1, minutes=30), 128, 58, 88, 48, 30, 38.9, 88, 0.65, 60, 320, 7.26, 11),
        ("vital3", "adm2", now - timedelta(hours=2, minutes=40), 108, 73, 112, 64, 26, 37.8, 91, 0.50, 68, None, 7.34, 14),
        ("vital4", "adm2", now - timedelta(hours=1), 116, 69, 106, 60, 32, 38.1, 87, 0.70, 59, 350, 7.31, 13),
        ("vital5", "adm3", now - timedelta(hours=4), 118, 65, 96, 56, 24, 37.2, 93, 0.40, 72, None, 7.36, 15),
        ("vital6", "adm3", now - timedelta(hours=1, minutes=20), 121, 62, 94, 54, 25, 37.5, 92, 0.45, 70, None, 7.34, 14),
    ]

    lab_events = [
        ("lab1", "adm1", now - timedelta(hours=2, minutes=50), "lactate", 4.6, "mmol/L", "high"),
        ("lab2", "adm1", now - timedelta(hours=1, minutes=20), "wbc", 19.2, "10^9/L", "high"),
        ("lab3", "adm2", now - timedelta(hours=2), "pao2", 59, "mmHg", "low"),
        ("lab4", "adm2", now - timedelta(minutes=55), "lactate", 2.8, "mmol/L", "high"),
        ("lab5", "adm3", now - timedelta(hours=3), "creatinine", 2.2, "mg/dL", "high"),
        ("lab6", "adm3", now - timedelta(hours=1), "lactate", 3.9, "mmol/L", "high"),
    ]

    intervention_events = [
        ("intv1", "adm1", now - timedelta(hours=2), "fluid", "500ml saline bolus", 500, "ml"),
        ("intv2", "adm1", now - timedelta(hours=1), "vasopressor", "norepinephrine up-titrated to 0.12 mcg/kg/min", 0.12, "mcg/kg/min"),
        ("intv3", "adm2", now - timedelta(hours=1, minutes=10), "ventilator_change", "PEEP increased from 8 to 12", 12, "cmH2O"),
        ("intv4", "adm3", now - timedelta(hours=2, minutes=30), "fluid", "500ml balanced crystalloid", 500, "ml"),
        ("intv5", "adm3", now - timedelta(minutes=50), "vasopressor", "norepinephrine started due to MAP drift", 0.06, "mcg/kg/min"),
    ]

    risk_assessments = [
        ("risk1", "adm1", now - timedelta(minutes=35), "shock", 0.92, "critical", [{"metric": "MAP", "trend": "down", "value": 58}, {"metric": "lactate", "value": 4.6}], "last_2h", "review fluid response and source control"),
        ("risk2", "adm2", now - timedelta(minutes=30), "respiratory_failure", 0.88, "critical", [{"metric": "SpO2", "value": 87}, {"metric": "PaO2", "value": 59}], "last_3h", "reassess ventilator settings and gas exchange"),
        ("risk3", "adm3", now - timedelta(minutes=25), "persistent_hypoperfusion", 0.81, "warning", [{"metric": "MAP", "value": 62}, {"metric": "lactate", "value": 3.9}], "last_4h", "monitor post-fluid hemodynamic response"),
    ]

    alerts = [
        ("alert1", "adm1", "p1", "b1", "shock_risk", "critical", "open", "risk_sentinel", [{"risk_id": "risk1"}], now - timedelta(minutes=35), now - timedelta(minutes=10)),
        ("alert2", "adm2", "p2", "b2", "resp_failure_risk", "critical", "open", "risk_sentinel", [{"risk_id": "risk2"}], now - timedelta(minutes=30), now - timedelta(minutes=8)),
        ("alert3", "adm3", "p3", "b3", "poor_fluid_response", "warning", "acknowledged", "risk_sentinel", [{"risk_id": "risk3"}], now - timedelta(minutes=25), now - timedelta(minutes=5)),
    ]

    state_current = [
        ("adm1", "p1", "b1", {"heart_rate": 128, "mean_arterial_pressure": 58, "spo2": 88}, ["septic_shock", "hypotension"], [{"risk_type": "shock", "severity": "critical"}], [{"intervention": "fluid_bolus", "response": "partial"}], "critical"),
        ("adm2", "p2", "b2", {"heart_rate": 116, "mean_arterial_pressure": 69, "spo2": 87}, ["oxygenation_worsening"], [{"risk_type": "respiratory_failure", "severity": "critical"}], [{"intervention": "peep_increase", "response": "pending"}], "critical"),
        ("adm3", "p3", "b3", {"heart_rate": 121, "mean_arterial_pressure": 62, "spo2": 92}, ["postop_hypoperfusion"], [{"risk_type": "persistent_hypoperfusion", "severity": "warning"}], [{"intervention": "fluid_bolus", "response": "non_responsive"}], "unstable"),
    ]

    snapshots = [
        ("snap1", "adm1", now - timedelta(hours=1), {"phase": "deteriorating", "map_trend": "down", "lactate": 4.6}),
        ("snap2", "adm2", now - timedelta(hours=1), {"phase": "resp_worsening", "spo2": 87, "fio2": 0.70}),
        ("snap3", "adm3", now - timedelta(hours=1), {"phase": "postop_monitoring", "fluid_response": "poor"}),
    ]

    audit_logs = [
        ("log1", now - timedelta(minutes=35), "agent", "risk_sentinel", "run_agent", "risk", "risk1", {"admission_id": "adm1"}, {"severity": "critical"}),
        ("log2", now - timedelta(minutes=30), "agent", "risk_sentinel", "run_agent", "risk", "risk2", {"admission_id": "adm2"}, {"severity": "critical"}),
        ("log3", now - timedelta(minutes=25), "agent", "risk_sentinel", "run_agent", "risk", "risk3", {"admission_id": "adm3"}, {"severity": "warning"}),
        ("log4", now - timedelta(minutes=9), "system", "alert_router", "update_state", "alert", "alert2", {"status": "open"}, {"queue": "high_priority"}),
    ]

    event_rows = [
        ("evt1", "adm1", "p1", "b1", "vital_sign", "monitor", now - timedelta(hours=1, minutes=30), "critical", {"vital_id": "vital2"}),
        ("evt2", "adm1", "p1", "b1", "lab", "lab", now - timedelta(hours=1, minutes=20), "high", {"lab_id": "lab2"}),
        ("evt3", "adm1", "p1", "b1", "intervention", "nurse", now - timedelta(hours=1), "high", {"intervention_id": "intv2"}),
        ("evt4", "adm2", "p2", "b2", "vital_sign", "monitor", now - timedelta(hours=1), "critical", {"vital_id": "vital4"}),
        ("evt5", "adm2", "p2", "b2", "intervention", "nurse", now - timedelta(hours=1, minutes=10), "high", {"intervention_id": "intv3"}),
        ("evt6", "adm3", "p3", "b3", "intervention", "nurse", now - timedelta(minutes=50), "normal", {"intervention_id": "intv5"}),
        ("evt7", "adm3", "p3", "b3", "agent_output", "agent", now - timedelta(minutes=25), "high", {"risk_id": "risk3", "type": "risk_assessment"}),
    ]

    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            # keep reruns deterministic for this seed set
            cur.execute(
                """
                DELETE FROM audit_logs WHERE id LIKE 'log%';
                DELETE FROM alerts WHERE alert_id LIKE 'alert%';
                DELETE FROM risk_assessments WHERE id LIKE 'risk%';
                DELETE FROM patient_state_snapshots WHERE id LIKE 'snap%';
                DELETE FROM patient_state_current WHERE admission_id IN ('adm1', 'adm2', 'adm3');
                DELETE FROM intervention_events WHERE id LIKE 'intv%';
                DELETE FROM lab_events WHERE id LIKE 'lab%';
                DELETE FROM vital_sign_events WHERE id LIKE 'vital%';
                DELETE FROM events WHERE event_id LIKE 'evt%';
                DELETE FROM admissions WHERE admission_id IN ('adm1', 'adm2', 'adm3');
                DELETE FROM beds WHERE bed_id IN ('b1', 'b2', 'b3', 'b4');
                DELETE FROM patients WHERE patient_id IN ('p1', 'p2', 'p3');
                """
            )

            cur.executemany(
                """
                INSERT INTO patients (
                    patient_id, patient_code, name, gender, age, date_of_birth, baseline_profile
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                [(a, b, c, d, e, f, j(g)) for (a, b, c, d, e, f, g) in patients],
            )
            cur.executemany(
                """
                INSERT INTO beds (
                    bed_id, bed_code, room_code, bed_type, status, notes
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                beds,
            )
            cur.executemany(
                """
                INSERT INTO admissions (
                    admission_id, patient_id, bed_id, admission_code, admit_time, discharge_time,
                    status, primary_diagnosis, admission_reason, severity_on_admission,
                    attending_team, scenario_tag
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                admissions,
            )
            cur.executemany(
                """
                INSERT INTO vital_sign_events (
                    id, admission_id, timestamp, heart_rate, mean_arterial_pressure, systolic_bp,
                    diastolic_bp, respiratory_rate, temperature, spo2, fio2, pao2, aado2, ph, gcs
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                vital_sign_events,
            )
            cur.executemany(
                """
                INSERT INTO lab_events (
                    id, admission_id, timestamp, lab_type, value, unit, abnormal_flag
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                lab_events,
            )
            cur.executemany(
                """
                INSERT INTO intervention_events (
                    id, admission_id, timestamp, intervention_type, description, dosage, unit
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                intervention_events,
            )
            cur.executemany(
                """
                INSERT INTO events (
                    event_id, admission_id, patient_id, bed_id, event_type, source, timestamp, priority, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                [(a, b, c, d, e, f, g, h, j(i)) for (a, b, c, d, e, f, g, h, i) in event_rows],
            )
            cur.executemany(
                """
                INSERT INTO patient_state_current (
                    admission_id, patient_id, bed_id, current_vitals, active_problems, active_risks,
                    latest_interventions, care_phase
                ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                """,
                [
                    (a, b, c, j(d), j(e), j(f), j(g), h)
                    for (a, b, c, d, e, f, g, h) in state_current
                ],
            )
            cur.executemany(
                """
                INSERT INTO patient_state_snapshots (
                    id, admission_id, timestamp, state_snapshot
                ) VALUES (%s, %s, %s, %s::jsonb)
                """,
                [(a, b, c, j(d)) for (a, b, c, d) in snapshots],
            )
            cur.executemany(
                """
                INSERT INTO risk_assessments (
                    id, admission_id, timestamp, risk_type, confidence, severity, evidence, time_window, recommended_action
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                [(a, b, c, d, e, f, j(g), h, i) for (a, b, c, d, e, f, g, h, i) in risk_assessments],
            )
            cur.executemany(
                """
                INSERT INTO alerts (
                    alert_id, admission_id, patient_id, bed_id, alert_type, severity, status,
                    source_agent, evidence, first_seen_at, last_seen_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                [(a, b, c, d, e, f, g, h, j(i), k, l) for (a, b, c, d, e, f, g, h, i, k, l) in alerts],
            )
            cur.executemany(
                """
                INSERT INTO audit_logs (
                    id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                [(a, b, c, d, e, f, g, j(h), j(i)) for (a, b, c, d, e, f, g, h, i) in audit_logs],
            )

            tables = [
                "patients", "beds", "admissions", "events", "vital_sign_events",
                "lab_events", "intervention_events", "patient_state_current",
                "patient_state_snapshots", "risk_assessments", "alerts", "audit_logs",
            ]
            counts: dict[str, int] = {}
            for table in tables:
                cur.execute(f"SELECT COUNT(*) FROM {table};")
                counts[table] = cur.fetchone()[0]

        conn.commit()

    print("Seed data inserted successfully.")
    for name, count in counts.items():
        print(f"- {name}: {count}")


if __name__ == "__main__":
    main()
