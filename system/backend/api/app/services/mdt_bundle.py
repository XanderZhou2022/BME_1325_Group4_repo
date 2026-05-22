from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row


class AdmissionNotFoundError(LookupError):
    pass


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _row_to_dict(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    return _jsonable(dict(row))


def _fetch_one(cur, sql: str, params: tuple) -> dict[str, Any] | None:
    cur.execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None


def _fetch_all(cur, sql: str, params: tuple) -> list[dict[str, Any]]:
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def build_icu_native_bundle(
    conn: Connection,
    admission_id: str,
    *,
    reason: str = "ICU manual MDT consultation",
    use_api: bool = False,
    questions_for_mdt: list[str] | None = None,
    labs_limit: int = 20,
    interventions_limit: int = 20,
    risks_limit: int = 10,
    agent_names: tuple[str, ...] = ("clinical_summary", "patient_memory"),
) -> dict[str, Any]:
    """Aggregate ICU DB rows into simi_hospital icu-native payload."""
    conn.row_factory = dict_row
    labs_limit = max(1, min(labs_limit, 100))
    interventions_limit = max(1, min(interventions_limit, 100))
    risks_limit = max(1, min(risks_limit, 50))

    with conn.cursor() as cur:
        admission = _fetch_one(
            cur,
            """
            SELECT admission_id, encounter_id, patient_id, bed_id, admission_code,
                   admit_time, discharge_time, status, encounter_status, primary_diagnosis,
                   admission_reason, severity_on_admission, attending_team,
                   scenario_tag, created_at, updated_at
            FROM admissions
            WHERE admission_id = %s
            """,
            (admission_id,),
        )
        if not admission:
            raise AdmissionNotFoundError(f"admission not found: {admission_id}")

        patient_id = str(admission["patient_id"])
        patient = _fetch_one(
            cur,
            """
            SELECT patient_id, patient_code, name, gender, age,
                   date_of_birth, contact, allergies, chronic_conditions, blood_type,
                   baseline_profile, created_at, updated_at
            FROM patients
            WHERE patient_id = %s
            """,
            (patient_id,),
        )
        if not patient:
            raise AdmissionNotFoundError(f"patient not found: {patient_id}")

        state = _fetch_one(
            cur,
            """
            SELECT admission_id, patient_id, bed_id, updated_at,
                   current_vitals, active_problems, active_risks, latest_interventions, care_phase
            FROM patient_state_current
            WHERE admission_id = %s
            """,
            (admission_id,),
        )

        lab_events = _fetch_all(
            cur,
            """
            SELECT id, admission_id, timestamp, lab_type, value, unit, abnormal_flag
            FROM lab_events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (admission_id, labs_limit),
        )

        intervention_events = _fetch_all(
            cur,
            """
            SELECT id, admission_id, timestamp, intervention_type, description, dosage, unit
            FROM intervention_events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (admission_id, interventions_limit),
        )

        alerts = _fetch_all(
            cur,
            """
            SELECT alert_id, admission_id, patient_id, bed_id, alert_type, severity, status,
                   source_agent, evidence, first_seen_at, last_seen_at
            FROM alerts
            WHERE admission_id = %s AND status = 'open'
            ORDER BY last_seen_at DESC
            """,
            (admission_id,),
        )

        risk_assessments = _fetch_all(
            cur,
            """
            SELECT id, admission_id, timestamp, risk_type, confidence, severity,
                   evidence, time_window, recommended_action
            FROM risk_assessments
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (admission_id, risks_limit),
        )

        agent_outputs: list[dict[str, Any]] = []
        for agent_name in agent_names:
            rows = _fetch_all(
                cur,
                """
                SELECT output_id, admission_id, patient_id, bed_id, agent_name, schema_version,
                       output_type, generated_at, payload
                FROM agent_outputs
                WHERE admission_id = %s AND agent_name = %s
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (admission_id, agent_name),
            )
            for row in rows:
                agent_outputs.append(
                    {
                        "agent_name": row["agent_name"],
                        "output_type": row.get("output_type"),
                        "schema_version": row.get("schema_version"),
                        "generated_at": row.get("generated_at"),
                        "payload": row.get("payload") or {},
                    }
                )

    bundle: dict[str, Any] = {
        "admission": _row_to_dict(admission),
        "patient": _row_to_dict(patient),
        "patient_state_current": _row_to_dict(state) if state else {
            "admission_id": admission_id,
            "patient_id": patient_id,
            "bed_id": admission.get("bed_id"),
            "current_vitals": {},
            "active_problems": [],
            "active_risks": [],
            "latest_interventions": [],
            "care_phase": "unknown",
        },
        "lab_events": [_row_to_dict(r) for r in lab_events],
        "intervention_events": [_row_to_dict(r) for r in intervention_events],
        "alerts": [_row_to_dict(r) for r in alerts],
        "risk_assessments": [_row_to_dict(r) for r in risk_assessments],
        "agent_outputs": [_jsonable(o) for o in agent_outputs],
        "reason": reason,
        "use_api": use_api,
    }
    if questions_for_mdt:
        bundle["questions_for_mdt"] = questions_for_mdt
    return bundle
