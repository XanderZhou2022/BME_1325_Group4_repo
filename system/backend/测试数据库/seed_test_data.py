from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os

import psycopg


DB_DSN = os.getenv("ICU_PG_DSN", "dbname=icu_agent user=zhou host=localhost port=5432")

# Contract v1.0 style IDs (deterministic for demos & tests)
P1, P2, P3 = "P-aaaaaaaa", "P-bbbbbbbb", "P-cccccccc"
E1, E2, E3 = "E-20260508100000-aaaa", "E-20260508100100-bbbb", "E-20260508100200-cccc"
B1, B2, B3, B4 = "B-ICU01-01", "B-ICU01-02", "B-ICU01-03", "B-ICU01-04"
ADM1, ADM2, ADM3 = "ICU-ADM-0001", "ICU-ADM-0002", "ICU-ADM-0003"


def j(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False)


def main() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)

    patients = [
        (
            P1,
            "P001",
            "Zhang San",
            "male",
            68,
            "1958-03-12",
            "13800000001",
            ["penicillin"],
            ["hypertension", "diabetes"],
            "O+",
            {"comorbidities": ["hypertension", "diabetes"], "allergies": ["penicillin"]},
        ),
        (
            P2,
            "P002",
            "Li Si",
            "female",
            57,
            "1969-08-20",
            "13900000002",
            [],
            ["copd"],
            "A+",
            {"comorbidities": ["copd"], "allergies": []},
        ),
        (
            P3,
            "P003",
            "Wang Wu",
            "male",
            72,
            "1954-01-09",
            "13700000003",
            [],
            ["ckd", "coronary_artery_disease"],
            "B+",
            {"comorbidities": ["ckd", "coronary_artery_disease"], "allergies": []},
        ),
    ]

    beds = [
        (B1, "ICU-01", "R-ICU-01", "standard", "occupied", None),
        (B2, "ICU-02", "R-ICU-01", "standard", "occupied", None),
        (B3, "ICU-03", "R-ICU-02", "isolation", "occupied", "contact isolation"),
        (B4, "ICU-04", "R-ICU-02", "standard", "empty", None),
    ]

    admissions = [
        (
            ADM1,
            E1,
            P1,
            B1,
            "ADM-001",
            now - timedelta(hours=26),
            None,
            "active",
            "ADMITTED",
            "septic shock",
            "ED transfer due to persistent hypotension",
            "critical",
            "ICU Team A",
            "sepsis_progressive",
        ),
        (
            ADM2,
            E2,
            P2,
            B2,
            "ADM-002",
            now - timedelta(hours=18),
            None,
            "active",
            "ADMITTED",
            "acute hypoxemic respiratory failure",
            "ward deterioration with increasing oxygen demand",
            "unstable",
            "ICU Team A",
            "resp_failure_worsening",
        ),
        (
            ADM3,
            E3,
            P3,
            B3,
            "ADM-003",
            now - timedelta(hours=40),
            None,
            "active",
            "ADMITTED",
            "post-op hemodynamic instability",
            "post-op monitoring with poor fluid response",
            "critical",
            "ICU Team B",
            "fluid_nonresponsive",
        ),
    ]

    vital_sign_events = [
        ("VS-20260508-10001", ADM1, now - timedelta(hours=3), 122, 61, 92, 52, 28, 38.6, 90, 0.60, 63, 280, 7.29, 12),
        ("VS-20260508-10002", ADM1, now - timedelta(hours=1, minutes=30), 128, 58, 88, 48, 30, 38.9, 88, 0.65, 60, 320, 7.26, 11),
        ("VS-20260508-10003", ADM2, now - timedelta(hours=2, minutes=40), 108, 73, 112, 64, 26, 37.8, 91, 0.50, 68, None, 7.34, 14),
        ("VS-20260508-10004", ADM2, now - timedelta(hours=1), 116, 69, 106, 60, 32, 38.1, 87, 0.70, 59, 350, 7.31, 13),
        ("VS-20260508-10005", ADM3, now - timedelta(hours=4), 118, 65, 96, 56, 24, 37.2, 93, 0.40, 72, None, 7.36, 15),
        ("VS-20260508-10006", ADM3, now - timedelta(hours=1, minutes=20), 121, 62, 94, 54, 25, 37.5, 92, 0.45, 70, None, 7.34, 14),
    ]

    lab_events = [
        ("LAB-20260508-10001", ADM1, now - timedelta(hours=2, minutes=50), "lactate", 4.6, "mmol/L", "high"),
        ("LAB-20260508-10002", ADM1, now - timedelta(hours=1, minutes=20), "wbc", 19.2, "10^9/L", "high"),
        ("LAB-20260508-10003", ADM2, now - timedelta(hours=2), "pao2", 59, "mmHg", "low"),
        ("LAB-20260508-10004", ADM2, now - timedelta(minutes=55), "lactate", 2.8, "mmol/L", "high"),
        ("LAB-20260508-10005", ADM3, now - timedelta(hours=3), "creatinine", 2.2, "mg/dL", "high"),
        ("LAB-20260508-10006", ADM3, now - timedelta(hours=1), "lactate", 3.9, "mmol/L", "high"),
    ]

    intervention_events = [
        ("INT-20260508-10001", ADM1, now - timedelta(hours=2), "fluid", "500ml saline bolus", 500, "ml"),
        ("INT-20260508-10002", ADM1, now - timedelta(hours=1), "vasopressor", "norepinephrine up-titrated to 0.12 mcg/kg/min", 0.12, "mcg/kg/min"),
        ("INT-20260508-10003", ADM2, now - timedelta(hours=1, minutes=10), "ventilator_change", "PEEP increased from 8 to 12", 12, "cmH2O"),
        ("INT-20260508-10004", ADM3, now - timedelta(hours=2, minutes=30), "fluid", "500ml balanced crystalloid", 500, "ml"),
        ("INT-20260508-10005", ADM3, now - timedelta(minutes=50), "vasopressor", "norepinephrine started due to MAP drift", 0.06, "mcg/kg/min"),
    ]

    risk_assessments = [
        ("risk1", ADM1, now - timedelta(minutes=35), "shock", 0.92, "critical", [{"metric": "MAP", "trend": "down", "value": 58}, {"metric": "lactate", "value": 4.6}], "last_2h", "review fluid response and source control"),
        ("risk2", ADM2, now - timedelta(minutes=30), "respiratory_failure", 0.88, "critical", [{"metric": "SpO2", "value": 87}, {"metric": "PaO2", "value": 59}], "last_3h", "reassess ventilator settings and gas exchange"),
        ("risk3", ADM3, now - timedelta(minutes=25), "persistent_hypoperfusion", 0.81, "warning", [{"metric": "MAP", "value": 62}, {"metric": "lactate", "value": 3.9}], "last_4h", "monitor post-fluid hemodynamic response"),
    ]

    alerts = [
        ("alert1", ADM1, P1, B1, "shock_risk", "critical", "open", "risk_sentinel", [{"risk_id": "risk1"}], now - timedelta(minutes=35), now - timedelta(minutes=10)),
        ("alert2", ADM2, P2, B2, "resp_failure_risk", "critical", "open", "risk_sentinel", [{"risk_id": "risk2"}], now - timedelta(minutes=30), now - timedelta(minutes=8)),
        ("alert3", ADM3, P3, B3, "poor_fluid_response", "warning", "acknowledged", "risk_sentinel", [{"risk_id": "risk3"}], now - timedelta(minutes=25), now - timedelta(minutes=5)),
    ]

    state_current = [
        (ADM1, P1, B1, {"heart_rate": 128, "mean_arterial_pressure": 58, "spo2": 88}, ["septic_shock", "hypotension"], [{"risk_type": "shock", "severity": "critical"}], [{"intervention": "fluid_bolus", "response": "partial"}], "critical"),
        (ADM2, P2, B2, {"heart_rate": 116, "mean_arterial_pressure": 69, "spo2": 87}, ["oxygenation_worsening"], [{"risk_type": "respiratory_failure", "severity": "critical"}], [{"intervention": "peep_increase", "response": "pending"}], "critical"),
        (ADM3, P3, B3, {"heart_rate": 121, "mean_arterial_pressure": 62, "spo2": 92}, ["postop_hypoperfusion"], [{"risk_type": "persistent_hypoperfusion", "severity": "warning"}], [{"intervention": "fluid_bolus", "response": "non_responsive"}], "unstable"),
    ]

    snapshots = [
        ("snap1", ADM1, now - timedelta(hours=1), {"phase": "deteriorating", "map_trend": "down", "lactate": 4.6}),
        ("snap2", ADM2, now - timedelta(hours=1), {"phase": "resp_worsening", "spo2": 87, "fio2": 0.70}),
        ("snap3", ADM3, now - timedelta(hours=1), {"phase": "postop_monitoring", "fluid_response": "poor"}),
    ]

    audit_logs = [
        ("log1", now - timedelta(minutes=35), "agent", "risk_sentinel", "run_agent", "risk", "risk1", {"admission_id": ADM1}, {"severity": "critical"}),
        ("log2", now - timedelta(minutes=30), "agent", "risk_sentinel", "run_agent", "risk", "risk2", {"admission_id": ADM2}, {"severity": "critical"}),
        ("log3", now - timedelta(minutes=25), "agent", "risk_sentinel", "run_agent", "risk", "risk3", {"admission_id": ADM3}, {"severity": "warning"}),
        ("log4", now - timedelta(minutes=9), "system", "alert_router", "update_state", "alert", "alert2", {"status": "open"}, {"queue": "high_priority"}),
    ]

    agent_outputs = [
        (
            "out_bedside_adm1",
            ADM1,
            P1,
            B1,
            "bedside_monitor",
            "v1",
            "bedside_analysis",
            now - timedelta(minutes=33),
            {
                "abnormal_flags": ["persistent_hypotension", "tachycardia"],
                "trend_labels": ["MAP_downtrend"],
                "urgency_level": "critical",
            },
        ),
        (
            "out_intervention_adm1",
            ADM1,
            P1,
            B1,
            "intervention_tracker",
            "v1",
            "intervention_evaluation",
            now - timedelta(minutes=31),
            {
                "response_assessment": "non_responsive",
                "intervention_type": "fluid",
                "observation_window": "pre 60m / post 60m",
            },
        ),
    ]

    evt_bed = "evt_01ABCDEFGHIJKLMNOPQRSTUV01"
    evt_int = "evt_01ABCDEFGHIJKLMNOPQRSTUV02"

    agent_events = [
        (
            evt_bed,
            ADM1,
            P1,
            B1,
            "bedside_monitor",
            "bedside_analysis_ready",
            "v1",
            now - timedelta(minutes=33),
            "out_bedside_adm1",
            {"agent_name": "bedside_monitor"},
        ),
        (
            evt_int,
            ADM1,
            P1,
            B1,
            "intervention_tracker",
            "intervention_evaluation_ready",
            "v1",
            now - timedelta(minutes=31),
            "out_intervention_adm1",
            {"agent_name": "intervention_tracker"},
        ),
    ]

    agent_registry = [
        ("bedside_monitor", ["vital_sign"], "bedside_analysis_ready", "v1", True),
        ("intervention_tracker", ["intervention"], "intervention_evaluation_ready", "v1", True),
        ("risk_sentinel", ["bedside_analysis_ready", "intervention_evaluation_ready"], "risk_assessment_ready", "v1", True),
    ]

    orchestrator_runs = [
        ("run_seed_1", now - timedelta(minutes=20), now - timedelta(minutes=19), [ADM1], [{"step_name": "risk_sentinel", "status": "ok"}]),
    ]

    agent_consumption_cursor = [
        ("risk_sentinel", ADM1, evt_int, now - timedelta(minutes=31)),
    ]

    # §4.3 envelope-style IDs: evt_ + exactly 26 [0-9A-Z] characters
    _ev = lambda n: "evt_" + str(n).zfill(26)
    event_rows = [
        (_ev(10000000000000000000000001), ADM1, P1, B1, "vital_sign", "monitor", now - timedelta(hours=1, minutes=30), "critical", {"vital_id": "VS-20260508-10002"}),
        (_ev(10000000000000000000000002), ADM1, P1, B1, "lab", "lab", now - timedelta(hours=1, minutes=20), "high", {"lab_id": "LAB-20260508-10002"}),
        (_ev(10000000000000000000000003), ADM1, P1, B1, "intervention", "nurse", now - timedelta(hours=1), "high", {"intervention_id": "INT-20260508-10002"}),
        (_ev(10000000000000000000000004), ADM2, P2, B2, "vital_sign", "monitor", now - timedelta(hours=1), "critical", {"vital_id": "VS-20260508-10004"}),
        (_ev(10000000000000000000000005), ADM2, P2, B2, "intervention", "nurse", now - timedelta(hours=1, minutes=10), "high", {"intervention_id": "INT-20260508-10003"}),
        (_ev(10000000000000000000000006), ADM3, P3, B3, "intervention", "nurse", now - timedelta(minutes=50), "normal", {"intervention_id": "INT-20260508-10005"}),
        (_ev(10000000000000000000000007), ADM3, P3, B3, "agent_output", "agent", now - timedelta(minutes=25), "high", {"risk_id": "risk3", "type": "risk_assessment"}),
    ]

    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            # Deterministic reseed: clear data tables (destructive by design).
            cur.execute(
                """
                TRUNCATE TABLE
                  intervention_pending,
                  agent_consumption_cursor,
                  agent_events,
                  agent_outputs,
                  clinical_summaries,
                  ward_priority_events,
                  ward_priority_snapshots,
                  patient_memory_events,
                  patient_memory,
                  patient_state_current,
                  patient_state_snapshots,
                  alerts,
                  risk_assessments,
                  events,
                  intervention_events,
                  lab_events,
                  vital_sign_events,
                  audit_logs,
                  orchestrator_runs,
                  admissions,
                  beds,
                  patients
                RESTART IDENTITY CASCADE
                """
            )
            cur.execute("DELETE FROM agent_registry")

            cur.executemany(
                """
                INSERT INTO patients (
                    patient_id, patient_code, name, gender, age, date_of_birth,
                    contact, allergies, chronic_conditions, blood_type, baseline_profile
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb)
                """,
                [
                    (a, b, c, d, e, f, g, j(h), j(i), k, j(l))
                    for (a, b, c, d, e, f, g, h, i, k, l) in patients
                ],
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
                    admission_id, encounter_id, patient_id, bed_id, admission_code, admit_time, discharge_time,
                    status, encounter_status, primary_diagnosis, admission_reason, severity_on_admission,
                    attending_team, scenario_tag
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            cur.executemany(
                """
                INSERT INTO agent_outputs (
                    output_id, admission_id, patient_id, bed_id, agent_name, schema_version,
                    output_type, generated_at, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                [
                    (a, b, c, d, e, f, g, h, j(i))
                    for (a, b, c, d, e, f, g, h, i) in agent_outputs
                ],
            )
            cur.executemany(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent, event_type,
                    schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                [
                    (a, b, c, d, e, f, g, h, i, j(k))
                    for (a, b, c, d, e, f, g, h, i, k) in agent_events
                ],
            )
            cur.executemany(
                """
                INSERT INTO agent_registry (
                    agent_name, input_event_types, output_event_type, schema_version, enabled
                ) VALUES (%s, %s::jsonb, %s, %s, %s)
                ON CONFLICT (agent_name) DO UPDATE SET
                    input_event_types = EXCLUDED.input_event_types,
                    output_event_type = EXCLUDED.output_event_type,
                    schema_version = EXCLUDED.schema_version,
                    enabled = EXCLUDED.enabled,
                    updated_at = NOW()
                """,
                [(a, j(b), c, d, e) for (a, b, c, d, e) in agent_registry],
            )
            cur.executemany(
                """
                INSERT INTO orchestrator_runs (
                    run_id, started_at, finished_at, target_admissions, step_results
                ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                [(a, b, c, j(d), j(e)) for (a, b, c, d, e) in orchestrator_runs],
            )
            cur.executemany(
                """
                INSERT INTO agent_consumption_cursor (
                    consumer_agent, admission_id, last_event_id, last_event_at
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (consumer_agent, admission_id) DO UPDATE SET
                    last_event_id = EXCLUDED.last_event_id,
                    last_event_at = EXCLUDED.last_event_at,
                    updated_at = NOW()
                """,
                agent_consumption_cursor,
            )

            tables = [
                "patients", "beds", "admissions", "events", "vital_sign_events",
                "lab_events", "intervention_events", "patient_state_current",
                "patient_state_snapshots", "agent_outputs", "agent_events",
                "agent_consumption_cursor", "agent_registry", "orchestrator_runs",
                "risk_assessments", "alerts", "audit_logs",
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
