from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.config import get_settings
from app.services.hospital_bus import publish_contract_event
from app.services.ids import new_id, new_transfer_id
from app.services.inpatient_client import InpatientBridgeError, post_icu_transfer_intake
from app.services.mdt_bundle import build_icu_native_bundle
from app.services.transfer_evaluator import evaluate_transfer_out


def _problems_as_list(state: dict[str, Any]) -> list[Any]:
    raw = state.get("active_problems") or []
    if isinstance(raw, list):
        return raw
    return []


def _risks_as_list(state: dict[str, Any]) -> list[Any]:
    raw = state.get("active_risks") or []
    if isinstance(raw, list):
        return raw
    return []


def build_transfer_payload(conn: Connection, admission_id: str, *, evaluation: dict[str, Any] | None = None) -> dict[str, Any]:
    bundle = build_icu_native_bundle(conn, admission_id, reason="ICU transfer to inpatient ward")
    admission = bundle["admission"]
    patient = bundle["patient"]
    state = bundle.get("patient_state_current") or {}
    ev = evaluation or evaluate_transfer_out(conn, admission_id)

    return {
        "source": get_settings().group_producer,
        "from_group": get_settings().group_producer,
        "transfer_intent": "to_inpatient",
        "icu_admission_id": admission_id,
        "icu_patient_id": admission.get("patient_id"),
        "patient_id": admission.get("patient_id"),
        "encounter_id": admission.get("encounter_id"),
        "bed_id": admission.get("bed_id") or state.get("bed_id"),
        "updated_at": state.get("updated_at") or datetime.now(timezone.utc).isoformat(),
        "care_phase": state.get("care_phase"),
        "current_vitals": state.get("current_vitals") or {},
        "active_problems": _problems_as_list(state),
        "active_risks": _risks_as_list(state),
        "latest_interventions": state.get("latest_interventions") or [],
        "ctas_level": ev.get("ctas_level"),
        "reason": ev.get("primary_reason"),
        "transfer_reasons": ev.get("reasons") or [],
        "patient_profile": {
            "patient_id": patient.get("patient_id"),
            "name": patient.get("name"),
            "gender": patient.get("gender"),
            "age": patient.get("age"),
            "contact": patient.get("contact"),
            "allergies": patient.get("allergies") or [],
            "chronic_conditions": patient.get("chronic_conditions") or [],
            "blood_type": patient.get("blood_type"),
        },
        "requested_resources": {"bed_type": "WARD", "monitor": True, "isolation": "standard"},
        "evaluation": ev,
    }


def persist_transfer_output(
    conn: Connection,
    *,
    admission_id: str,
    patient_id: str,
    bed_id: str,
    evaluation: dict[str, Any],
    bridge_response: dict[str, Any],
    transfer_id: str,
) -> str:
    output_id = new_id("out")
    now = datetime.now(timezone.utc)
    payload = {
        "transfer_id": transfer_id,
        "target_group": "groupD.inpatient",
        "evaluation": evaluation,
        "bridge_response": bridge_response,
        "transfer_reason": evaluation.get("primary_reason"),
        "transfer_reasons": evaluation.get("reasons") or [],
        "blockers_at_transfer": evaluation.get("blockers") or [],
        "assigned_bed": bridge_response.get("assigned_bed"),
        "assigned_room": bridge_response.get("assigned_room"),
        "inpatient_patient_id": bridge_response.get("patient_id"),
        "inpatient_encounter_id": bridge_response.get("encounter_id"),
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_outputs (
                output_id, admission_id, patient_id, bed_id, agent_name,
                schema_version, output_type, generated_at, payload
            ) VALUES (%s, %s, %s, %s, 'inpatient_transfer', 'icu_to_inpatient.v1', 'transfer_completed', %s, %s::jsonb)
            """,
            (output_id, admission_id, patient_id, bed_id, now, Json(payload)),
        )
        event_id = new_id("aevt")
        cur.execute(
            """
            INSERT INTO agent_events (
                event_id, admission_id, patient_id, bed_id, producer_agent,
                event_type, schema_version, produced_at, output_id, payload
            ) VALUES (%s, %s, %s, %s, 'inpatient_transfer', 'inpatient_transfer_completed', 'icu_to_inpatient.v1', %s, %s, %s::jsonb)
            """,
            (
                event_id,
                admission_id,
                patient_id,
                bed_id,
                now,
                output_id,
                Json({"output_id": output_id, "transfer_id": transfer_id, "reason": evaluation.get("primary_reason")}),
            ),
        )
    return output_id


def execute_transfer_out(
    conn: Connection,
    admission_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    evaluation = evaluate_transfer_out(conn, admission_id)
    if not evaluation.get("eligible") and not force:
        return {
            "status": "rejected",
            "evaluation": evaluation,
            "message": evaluation.get("primary_reason") or "未满足转出条件",
        }

    payload = build_transfer_payload(conn, admission_id, evaluation=evaluation)
    transfer_id = new_transfer_id()

    try:
        bridge = post_icu_transfer_intake(payload)
    except InpatientBridgeError as exc:
        return {
            "status": "bridge_error",
            "evaluation": evaluation,
            "transfer_id": transfer_id,
            "message": exc.message,
            "error_code": exc.code,
        }

    conn.row_factory = dict_row
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "SELECT patient_id, bed_id, encounter_id FROM admissions WHERE admission_id = %s",
                (admission_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"status": "not_found", "evaluation": evaluation}
            patient_id = str(row["patient_id"])
            bed_id = str(row["bed_id"])
            encounter_id = str(row["encounter_id"])

            cur.execute(
                """
                UPDATE admissions
                SET status = 'transferred',
                    encounter_status = 'TRANSFERRING',
                    discharge_time = %s,
                    updated_at = NOW()
                WHERE admission_id = %s
                """,
                (datetime.now(timezone.utc), admission_id),
            )
            cur.execute("UPDATE beds SET status = 'empty', updated_at = NOW() WHERE bed_id = %s", (bed_id,))

        output_id = persist_transfer_output(
            conn,
            admission_id=admission_id,
            patient_id=patient_id,
            bed_id=bed_id,
            evaluation=evaluation,
            bridge_response=bridge,
            transfer_id=transfer_id,
        )

    xfer_data: dict[str, Any] = {
        "transfer_id": transfer_id,
        "from_group": get_settings().group_producer,
        "to_group": "groupD.inpatient",
        "icu_admission_id": admission_id,
        "reason": evaluation.get("primary_reason"),
        "transfer_reasons": evaluation.get("reasons") or [],
        "assigned_bed": bridge.get("assigned_bed"),
        "assigned_room": bridge.get("assigned_room"),
        "ctas_level": evaluation.get("ctas_level"),
    }
    publish_contract_event(
        event_type="patient.transferred",
        patient_id=patient_id,
        encounter_id=encounter_id,
        data=xfer_data,
        durable=True,
    )

    return {
        "status": "accepted",
        "transfer_id": transfer_id,
        "evaluation": evaluation,
        "bridge_response": bridge,
        "output_id": output_id,
        "message": evaluation.get("primary_reason"),
    }
