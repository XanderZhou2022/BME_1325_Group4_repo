from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.schemas import (
    InterventionEventCreate,
    LabEventCreate,
    VitalSignEventCreate,
)
from app.services.ids import new_id
from app.services.state_merge import (
    infer_care_phase_from_vitals,
    json_or_obj,
    merge_intervention_into_latest,
    merge_lab_into_problems,
    merge_vitals_into_current,
)


def _audit(
    cur: Any,
    *,
    actor: str,
    actor_id: str,
    action_type: str,
    target_type: str,
    target_id: str,
    input_obj: dict[str, Any],
    output_obj: dict[str, Any],
) -> None:
    log_id = new_id("log")
    cur.execute(
        """
        INSERT INTO audit_logs (
            id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
        """,
        (
            log_id,
            datetime.now(timezone.utc),
            actor,
            actor_id,
            action_type,
            target_type,
            target_id,
            Json(input_obj),
            Json(output_obj),
        ),
    )


def _get_admission(cur: Any, admission_id: str) -> dict[str, Any]:
    cur.row_factory = dict_row
    cur.execute(
        """
        SELECT admission_id, patient_id, bed_id, status
        FROM admissions
        WHERE admission_id = %s
        """,
        (admission_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="admission not found")
    if row["status"] != "active":
        raise HTTPException(status_code=409, detail="admission is not active")
    return row


def _get_or_init_state(cur: Any, admission: dict[str, Any]) -> dict[str, Any]:
    cur.execute(
        """
        SELECT admission_id, patient_id, bed_id, updated_at,
               current_vitals, active_problems, active_risks, latest_interventions, care_phase
        FROM patient_state_current
        WHERE admission_id = %s
        """,
        (admission["admission_id"],),
    )
    row = cur.fetchone()
    if row:
        return {
            "admission_id": row["admission_id"],
            "patient_id": row["patient_id"],
            "bed_id": row["bed_id"],
            "current_vitals": json_or_obj(row["current_vitals"]) or {},
            "active_problems": json_or_obj(row["active_problems"]) or [],
            "active_risks": json_or_obj(row["active_risks"]) or [],
            "latest_interventions": json_or_obj(row["latest_interventions"]) or [],
            "care_phase": row["care_phase"],
        }
    return {
        "admission_id": admission["admission_id"],
        "patient_id": admission["patient_id"],
        "bed_id": admission["bed_id"],
        "current_vitals": {},
        "active_problems": [],
        "active_risks": [],
        "latest_interventions": [],
        "care_phase": "stable",
    }


def _upsert_state(
    cur: Any,
    state: dict[str, Any],
) -> None:
    cur.execute(
        """
        INSERT INTO patient_state_current (
            admission_id, patient_id, bed_id, updated_at,
            current_vitals, active_problems, active_risks, latest_interventions, care_phase
        ) VALUES (%s, %s, %s, NOW(), %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s)
        ON CONFLICT (admission_id) DO UPDATE SET
            patient_id = EXCLUDED.patient_id,
            bed_id = EXCLUDED.bed_id,
            updated_at = NOW(),
            current_vitals = EXCLUDED.current_vitals,
            active_problems = EXCLUDED.active_problems,
            active_risks = EXCLUDED.active_risks,
            latest_interventions = EXCLUDED.latest_interventions,
            care_phase = EXCLUDED.care_phase
        """,
        (
            state["admission_id"],
            state["patient_id"],
            state["bed_id"],
            Json(state["current_vitals"]),
            Json(state["active_problems"]),
            Json(state["active_risks"]),
            Json(state["latest_interventions"]),
            state["care_phase"],
        ),
    )


def write_vital_sign(
    conn: Connection,
    admission_id: str,
    body: VitalSignEventCreate,
) -> dict[str, str]:
    detail_id = new_id("vital")
    event_id = new_id("evt")
    with conn.transaction():
        cur = conn.cursor()
        admission = _get_admission(cur, admission_id)
        state = _get_or_init_state(cur, admission)

        cur.execute(
            """
            INSERT INTO vital_sign_events (
                id, admission_id, timestamp, heart_rate, mean_arterial_pressure,
                systolic_bp, diastolic_bp, respiratory_rate, temperature, spo2,
                fio2, pao2, aado2, ph, gcs
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                detail_id,
                admission_id,
                body.timestamp,
                body.heart_rate,
                body.mean_arterial_pressure,
                body.systolic_bp,
                body.diastolic_bp,
                body.respiratory_rate,
                body.temperature,
                body.spo2,
                body.fio2,
                body.pao2,
                body.aado2,
                body.ph,
                body.gcs,
            ),
        )

        payload = {"vital_id": detail_id, "kind": "vital_sign"}
        cur.execute(
            """
            INSERT INTO events (
                event_id, admission_id, patient_id, bed_id, event_type, source, timestamp, priority, payload
            ) VALUES (%s, %s, %s, %s, 'vital_sign', %s, %s, %s, %s::jsonb)
            """,
            (
                event_id,
                admission_id,
                admission["patient_id"],
                admission["bed_id"],
                body.source,
                body.timestamp,
                body.priority,
                Json(payload),
            ),
        )

        new_vitals = {
            "heart_rate": body.heart_rate,
            "mean_arterial_pressure": body.mean_arterial_pressure,
            "systolic_bp": body.systolic_bp,
            "diastolic_bp": body.diastolic_bp,
            "respiratory_rate": body.respiratory_rate,
            "temperature": body.temperature,
            "spo2": body.spo2,
            "fio2": body.fio2,
            "pao2": body.pao2,
            "aado2": body.aado2,
            "ph": body.ph,
            "gcs": body.gcs,
        }
        merged = merge_vitals_into_current(state["current_vitals"], new_vitals)
        state["current_vitals"] = merged
        state["care_phase"] = infer_care_phase_from_vitals(merged)
        _upsert_state(cur, state)

        _audit(
            cur,
            actor="system",
            actor_id="api",
            action_type="create_event",
            target_type="event",
            target_id=event_id,
            input_obj={"admission_id": admission_id, "type": "vital_sign", "detail_id": detail_id},
            output_obj={"event_id": event_id, "detail_id": detail_id},
        )
        _audit(
            cur,
            actor="system",
            actor_id="api",
            action_type="update_state",
            target_type="patient_state",
            target_id=admission_id,
            input_obj={"admission_id": admission_id, "trigger": "vital_sign"},
            output_obj={"care_phase": state["care_phase"]},
        )

    return {
        "event_id": event_id,
        "detail_id": detail_id,
        "admission_id": admission_id,
        "patient_id": admission["patient_id"],
        "bed_id": admission["bed_id"],
    }


def write_lab(
    conn: Connection,
    admission_id: str,
    body: LabEventCreate,
) -> dict[str, str]:
    detail_id = new_id("lab")
    event_id = new_id("evt")
    with conn.transaction():
        cur = conn.cursor()
        admission = _get_admission(cur, admission_id)
        state = _get_or_init_state(cur, admission)

        cur.execute(
            """
            INSERT INTO lab_events (
                id, admission_id, timestamp, lab_type, value, unit, abnormal_flag
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                detail_id,
                admission_id,
                body.timestamp,
                body.lab_type,
                body.value,
                body.unit,
                body.abnormal_flag,
            ),
        )

        payload = {"lab_id": detail_id, "kind": "lab"}
        cur.execute(
            """
            INSERT INTO events (
                event_id, admission_id, patient_id, bed_id, event_type, source, timestamp, priority, payload
            ) VALUES (%s, %s, %s, %s, 'lab', %s, %s, %s, %s::jsonb)
            """,
            (
                event_id,
                admission_id,
                admission["patient_id"],
                admission["bed_id"],
                body.source,
                body.timestamp,
                body.priority,
                Json(payload),
            ),
        )

        state["active_problems"] = merge_lab_into_problems(
            state["active_problems"], body.lab_type, body.abnormal_flag
        )
        if body.abnormal_flag != "normal" and state["care_phase"] == "stable":
            state["care_phase"] = "unstable"
        _upsert_state(cur, state)

        _audit(
            cur,
            actor="system",
            actor_id="api",
            action_type="create_event",
            target_type="event",
            target_id=event_id,
            input_obj={"admission_id": admission_id, "type": "lab", "detail_id": detail_id},
            output_obj={"event_id": event_id, "detail_id": detail_id},
        )
        _audit(
            cur,
            actor="system",
            actor_id="api",
            action_type="update_state",
            target_type="patient_state",
            target_id=admission_id,
            input_obj={"admission_id": admission_id, "trigger": "lab"},
            output_obj={"care_phase": state["care_phase"]},
        )

    return {
        "event_id": event_id,
        "detail_id": detail_id,
        "admission_id": admission_id,
        "patient_id": admission["patient_id"],
        "bed_id": admission["bed_id"],
    }


def write_intervention(
    conn: Connection,
    admission_id: str,
    body: InterventionEventCreate,
) -> dict[str, str]:
    detail_id = new_id("intv")
    event_id = new_id("evt")
    with conn.transaction():
        cur = conn.cursor()
        admission = _get_admission(cur, admission_id)
        state = _get_or_init_state(cur, admission)

        cur.execute(
            """
            INSERT INTO intervention_events (
                id, admission_id, timestamp, intervention_type, description, dosage, unit
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                detail_id,
                admission_id,
                body.timestamp,
                body.intervention_type,
                body.description,
                body.dosage,
                body.unit,
            ),
        )

        payload = {"intervention_id": detail_id, "kind": "intervention"}
        cur.execute(
            """
            INSERT INTO events (
                event_id, admission_id, patient_id, bed_id, event_type, source, timestamp, priority, payload
            ) VALUES (%s, %s, %s, %s, 'intervention', %s, %s, %s, %s::jsonb)
            """,
            (
                event_id,
                admission_id,
                admission["patient_id"],
                admission["bed_id"],
                body.source,
                body.timestamp,
                body.priority,
                Json(payload),
            ),
        )

        item = {
            "id": detail_id,
            "intervention_type": body.intervention_type,
            "description": body.description,
            "timestamp": body.timestamp.isoformat(),
        }
        state["latest_interventions"] = merge_intervention_into_latest(
            state["latest_interventions"], item
        )
        _upsert_state(cur, state)

        _audit(
            cur,
            actor="system",
            actor_id="api",
            action_type="create_event",
            target_type="event",
            target_id=event_id,
            input_obj={"admission_id": admission_id, "type": "intervention", "detail_id": detail_id},
            output_obj={"event_id": event_id, "detail_id": detail_id},
        )
        _audit(
            cur,
            actor="system",
            actor_id="api",
            action_type="update_state",
            target_type="patient_state",
            target_id=admission_id,
            input_obj={"admission_id": admission_id, "trigger": "intervention"},
            output_obj={"care_phase": state["care_phase"]},
        )

    return {
        "event_id": event_id,
        "detail_id": detail_id,
        "admission_id": admission_id,
        "patient_id": admission["patient_id"],
        "bed_id": admission["bed_id"],
    }
