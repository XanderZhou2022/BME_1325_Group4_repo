from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.sql import SQL, Identifier
from psycopg.types.json import Json

from app.db import get_db
from app.schemas import (
    AlertOut,
    AdmissionOut,
    AdmissionCreate,
    AdmissionStatusUpdate,
    TableRowPreview,
    AuditLogOut,
    BedOut,
    EventOut,
    EventWriteResult,
    InterventionEventCreate,
    InterventionEventOut,
    LabEventCreate,
    LabEventOut,
    PatientOut,
    DbHealthOut,
    AgentCursorOut,
    AgentEventOut,
    AgentOutputOut,
    PatientStateCurrentOut,
    PatientStateSnapshotOut,
    RiskAssessmentOut,
    VitalSignEventCreate,
    VitalSignEventOut,
    TransferRequestBody,
    TransferAcceptedData,
)
from app.services.event_pipeline import (
    write_intervention,
    write_lab,
    write_vital_sign,
)
from app.orchestrator.event_dispatcher import dispatch_event_chain
from app.services.hospital_bus import publish_contract_event
from app.services.idempotency import get_cached_response, store_response
from app.services.ids import new_icu_admission_id, new_transfer_id

router = APIRouter(prefix="/api/v1")

_ENCOUNTER_ID_RE = re.compile(r"^E-\d{14}-[0-9a-f]{4}$")
_PATIENT_ID_RE = re.compile(r"^P-[0-9a-f]{8}$")


def _raise_id_malformed(field: str) -> None:
    raise HTTPException(
        status_code=400,
        detail={"code": "ID_MALFORMED", "message": f"invalid {field} format"},
    )

# === Agent-layer: bedside-level, rule-driven modules ===
from agents.bedside_monitor.router import router as bedside_monitor_router
from agents.intervention_tracker.router import router as intervention_tracker_router
from agents.patient_memory.router import router as patient_memory_router
from agents.clinical_summary.router import router as clinical_summary_router
from agents.ward_coordinator.router import router as ward_coordinator_router
from agents.risk_sentinel.router import router as risk_sentinel_router
from agents.compassion_family_communication.router import router as compassion_family_router
from app.orchestrator.router import router as orchestrator_router
from app.demo.router import router as demo_auto_router
from app.mdt.router import router as mdt_consultation_router

router.include_router(bedside_monitor_router)
router.include_router(intervention_tracker_router)
router.include_router(patient_memory_router)
router.include_router(clinical_summary_router)
router.include_router(ward_coordinator_router)
router.include_router(risk_sentinel_router)
router.include_router(compassion_family_router)
router.include_router(orchestrator_router)
router.include_router(demo_auto_router)
router.include_router(mdt_consultation_router)


# === Write-side: events driving state ===


@router.post(
    "/admissions/{admission_id}/events/vital_sign",
    response_model=EventWriteResult,
)
def post_vital_sign(
    admission_id: str,
    body: VitalSignEventCreate,
    conn: Connection = Depends(get_db),
) -> EventWriteResult:
    out = write_vital_sign(conn, admission_id, body)
    dispatch_event_chain(conn, admission_id=admission_id, event_type="vital_sign", detail_id=out["detail_id"])
    return EventWriteResult(**out)


@router.post("/admissions/{admission_id}/events/lab", response_model=EventWriteResult)
def post_lab(
    admission_id: str,
    body: LabEventCreate,
    conn: Connection = Depends(get_db),
) -> EventWriteResult:
    out = write_lab(conn, admission_id, body)
    dispatch_event_chain(conn, admission_id=admission_id, event_type="lab", detail_id=out["detail_id"])
    return EventWriteResult(**out)


@router.post(
    "/admissions/{admission_id}/events/intervention",
    response_model=EventWriteResult,
)
def post_intervention(
    admission_id: str,
    body: InterventionEventCreate,
    conn: Connection = Depends(get_db),
) -> EventWriteResult:
    out = write_intervention(conn, admission_id, body)
    dispatch_event_chain(conn, admission_id=admission_id, event_type="intervention", detail_id=out["detail_id"])
    return EventWriteResult(**out)


# === Read-side: current state, alerts, risks ===


@router.get("/admissions/{admission_id}/state/current", response_model=PatientStateCurrentOut)
def get_current_state(
    admission_id: str,
    conn: Connection = Depends(get_db),
) -> PatientStateCurrentOut:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT admission_id, patient_id, bed_id, updated_at,
                   current_vitals, active_problems, active_risks, latest_interventions, care_phase
            FROM patient_state_current
            WHERE admission_id = %s
            """,
            (admission_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="patient_state_current not found for admission")
    return PatientStateCurrentOut(
        admission_id=row["admission_id"],
        patient_id=row["patient_id"],
        bed_id=row["bed_id"],
        updated_at=row["updated_at"],
        current_vitals=row["current_vitals"] or {},
        active_problems=row["active_problems"] or [],
        active_risks=row["active_risks"] or [],
        latest_interventions=row["latest_interventions"] or [],
        care_phase=row["care_phase"],
    )


@router.get("/admissions/{admission_id}/alerts", response_model=list[AlertOut])
def list_alerts(
    admission_id: str,
    conn: Connection = Depends(get_db),
) -> list[AlertOut]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT alert_id, admission_id, patient_id, bed_id, alert_type, severity, status,
                   source_agent, evidence, first_seen_at, last_seen_at
            FROM alerts
            WHERE admission_id = %s
            ORDER BY last_seen_at DESC
            """,
            (admission_id,),
        )
        rows = cur.fetchall()
    return [
        AlertOut(
            alert_id=r["alert_id"],
            admission_id=r["admission_id"],
            patient_id=r["patient_id"],
            bed_id=r["bed_id"],
            alert_type=r["alert_type"],
            severity=r["severity"],
            status=r["status"],
            source_agent=r["source_agent"],
            evidence=r["evidence"] or [],
            first_seen_at=r["first_seen_at"],
            last_seen_at=r["last_seen_at"],
        )
        for r in rows
    ]


@router.get("/admissions/{admission_id}/risks", response_model=list[RiskAssessmentOut])
def list_risks(
    admission_id: str,
    conn: Connection = Depends(get_db),
) -> list[RiskAssessmentOut]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, admission_id, timestamp, risk_type, confidence, severity,
                   evidence, time_window, recommended_action
            FROM risk_assessments
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            """,
            (admission_id,),
        )
        rows = cur.fetchall()
    out: list[RiskAssessmentOut] = []
    for r in rows:
        out.append(
            RiskAssessmentOut(
                id=r["id"],
                admission_id=r["admission_id"],
                timestamp=r["timestamp"],
                risk_type=r["risk_type"],
                confidence=r["confidence"],
                severity=r["severity"],
                evidence=r["evidence"] or [],
                time_window=r["time_window"],
                recommended_action=r["recommended_action"],
            )
        )
    return out


# === Read-side: core entities & history (for debugging / agents) ===


@router.get("/patients/{patient_id}", response_model=PatientOut)
def get_patient(
    patient_id: str,
    conn: Connection = Depends(get_db),
) -> PatientOut:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT patient_id, patient_code, name, gender, age,
                   date_of_birth, contact, allergies, chronic_conditions, blood_type,
                   baseline_profile, created_at, updated_at
            FROM patients
            WHERE patient_id = %s
            """,
            (patient_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="patient not found")
    return PatientOut(**row)


@router.get("/beds/{bed_id}", response_model=BedOut)
def get_bed(
    bed_id: str,
    conn: Connection = Depends(get_db),
) -> BedOut:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT bed_id, bed_code, room_code, bed_type, status,
                   notes, created_at, updated_at
            FROM beds
            WHERE bed_id = %s
            """,
            (bed_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="bed not found")
    return BedOut(**row)


@router.get("/admissions/{admission_id}", response_model=AdmissionOut)
def get_admission(
    admission_id: str,
    conn: Connection = Depends(get_db),
) -> AdmissionOut:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
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
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="admission not found")
    return AdmissionOut(**row)


@router.get("/admissions/{admission_id}/events", response_model=list[EventOut])
def list_events(
    admission_id: str,
    limit: int = 50,
    conn: Connection = Depends(get_db),
) -> list[EventOut]:
    limit = max(1, min(limit, 200))
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_id, admission_id, patient_id, bed_id, event_type, source,
                   timestamp, priority, payload
            FROM events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (admission_id, limit),
        )
        rows = cur.fetchall()
    return [EventOut(**r) for r in rows]


@router.get(
    "/admissions/{admission_id}/vitals",
    response_model=list[VitalSignEventOut],
)
def list_vitals(
    admission_id: str,
    limit: int = 100,
    conn: Connection = Depends(get_db),
) -> list[VitalSignEventOut]:
    limit = max(1, min(limit, 500))
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, admission_id, timestamp, heart_rate, mean_arterial_pressure,
                   systolic_bp, diastolic_bp, respiratory_rate, temperature, spo2,
                   fio2, pao2, aado2, ph, gcs
            FROM vital_sign_events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (admission_id, limit),
        )
        rows = cur.fetchall()
    return [VitalSignEventOut(**r) for r in rows]


@router.get(
    "/admissions/{admission_id}/labs",
    response_model=list[LabEventOut],
)
def list_labs(
    admission_id: str,
    limit: int = 100,
    conn: Connection = Depends(get_db),
) -> list[LabEventOut]:
    limit = max(1, min(limit, 500))
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, admission_id, timestamp, lab_type, value, unit, abnormal_flag
            FROM lab_events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (admission_id, limit),
        )
        rows = cur.fetchall()
    return [LabEventOut(**r) for r in rows]


@router.get(
    "/admissions/{admission_id}/interventions",
    response_model=list[InterventionEventOut],
)
def list_interventions(
    admission_id: str,
    limit: int = 100,
    conn: Connection = Depends(get_db),
) -> list[InterventionEventOut]:
    limit = max(1, min(limit, 500))
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, admission_id, timestamp, intervention_type, description, dosage, unit
            FROM intervention_events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (admission_id, limit),
        )
        rows = cur.fetchall()
    return [InterventionEventOut(**r) for r in rows]


@router.get(
    "/admissions/{admission_id}/snapshots",
    response_model=list[PatientStateSnapshotOut],
)
def list_snapshots(
    admission_id: str,
    limit: int = 50,
    conn: Connection = Depends(get_db),
) -> list[PatientStateSnapshotOut]:
    limit = max(1, min(limit, 200))
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, admission_id, timestamp, state_snapshot
            FROM patient_state_snapshots
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (admission_id, limit),
        )
        rows = cur.fetchall()
    return [PatientStateSnapshotOut(**r) for r in rows]


@router.get(
    "/admissions/{admission_id}/audit_logs",
    response_model=list[AuditLogOut],
)
def list_audit_logs(
    admission_id: str,
    limit: int = 100,
    conn: Connection = Depends(get_db),
) -> list[AuditLogOut]:
    limit = max(1, min(limit, 500))
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output
            FROM audit_logs
            WHERE target_type IN ('event', 'patient_state', 'risk', 'alert') AND input ->> 'admission_id' = %s
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (admission_id, limit),
        )
        rows = cur.fetchall()
    return [AuditLogOut(**r) for r in rows]


@router.get("/admissions/{admission_id}/agent_outputs", response_model=list[AgentOutputOut])
def list_agent_outputs(
    admission_id: str,
    agent_name: str | None = None,
    limit: int = 100,
    conn: Connection = Depends(get_db),
) -> list[AgentOutputOut]:
    limit = max(1, min(limit, 500))
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        if agent_name:
            cur.execute(
                """
                SELECT output_id, admission_id, patient_id, bed_id, agent_name, schema_version,
                       output_type, generated_at, payload
                FROM agent_outputs
                WHERE admission_id = %s AND agent_name = %s
                ORDER BY generated_at DESC
                LIMIT %s
                """,
                (admission_id, agent_name, limit),
            )
        else:
            cur.execute(
                """
                SELECT output_id, admission_id, patient_id, bed_id, agent_name, schema_version,
                       output_type, generated_at, payload
                FROM agent_outputs
                WHERE admission_id = %s
                ORDER BY generated_at DESC
                LIMIT %s
                """,
                (admission_id, limit),
            )
        rows = cur.fetchall()
    out: list[AgentOutputOut] = []
    for r in rows:
        row = dict(r)
        row["payload"] = row.get("payload") or {}
        out.append(AgentOutputOut(**row))
    return out


@router.get("/admissions/{admission_id}/agent_events", response_model=list[AgentEventOut])
def list_agent_events(
    admission_id: str,
    producer_agent: str | None = None,
    limit: int = 100,
    conn: Connection = Depends(get_db),
) -> list[AgentEventOut]:
    limit = max(1, min(limit, 500))
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        if producer_agent:
            cur.execute(
                """
                SELECT event_id, admission_id, patient_id, bed_id, producer_agent, event_type,
                       schema_version, produced_at, output_id, payload
                FROM agent_events
                WHERE admission_id = %s AND producer_agent = %s
                ORDER BY produced_at DESC
                LIMIT %s
                """,
                (admission_id, producer_agent, limit),
            )
        else:
            cur.execute(
                """
                SELECT event_id, admission_id, patient_id, bed_id, producer_agent, event_type,
                       schema_version, produced_at, output_id, payload
                FROM agent_events
                WHERE admission_id = %s
                ORDER BY produced_at DESC
                LIMIT %s
                """,
                (admission_id, limit),
            )
        rows = cur.fetchall()
    out: list[AgentEventOut] = []
    for r in rows:
        row = dict(r)
        row["payload"] = row.get("payload") or {}
        out.append(AgentEventOut(**row))
    return out


@router.get("/admissions/{admission_id}/agent_cursors", response_model=list[AgentCursorOut])
def list_agent_cursors(
    admission_id: str,
    conn: Connection = Depends(get_db),
) -> list[AgentCursorOut]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT consumer_agent, admission_id, last_event_id, last_event_at, updated_at
            FROM agent_consumption_cursor
            WHERE admission_id = %s
            ORDER BY consumer_agent ASC
            """,
            (admission_id,),
        )
        rows = cur.fetchall()
    return [AgentCursorOut(**r) for r in rows]


@router.get("/ops/db-health", response_model=DbHealthOut)
def get_db_health(conn: Connection = Depends(get_db)) -> DbHealthOut:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT NOW() AT TIME ZONE 'UTC' AS server_time_utc")
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="database health query failed")
    return DbHealthOut(status="ok", database="postgresql", server_time_utc=row["server_time_utc"])



@router.post("/admissions", response_model=AdmissionOut)
def create_admission(
    body: AdmissionCreate,
    conn: Connection = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AdmissionOut:
    route_key = "POST /api/v1/admissions"
    conn.row_factory = dict_row
    if idempotency_key:
        cached = get_cached_response(conn, key=idempotency_key, route=route_key)
        if cached:
            return AdmissionOut(**cached)
    if not _PATIENT_ID_RE.match(body.patient_id):
        _raise_id_malformed("patient_id")
    if not _ENCOUNTER_ID_RE.match(body.encounter_id):
        _raise_id_malformed("encounter_id")

    with conn.transaction():
        with conn.cursor() as cur:
            if body.patient_profile is None:
                cur.execute("SELECT 1 FROM patients WHERE patient_id = %s", (body.patient_id,))
                if not cur.fetchone():
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "code": "ENCOUNTER_NOT_FOUND",
                            "message": "patient not found; include patient_profile to create the patient first",
                        },
                    )
            if body.patient_profile is not None:
                pp = body.patient_profile
                cur.execute(
                    """
                    INSERT INTO patients (
                        patient_id, patient_code, name, gender, age, date_of_birth,
                        contact, allergies, chronic_conditions, blood_type, baseline_profile
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb)
                    ON CONFLICT (patient_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        gender = EXCLUDED.gender,
                        age = EXCLUDED.age,
                        date_of_birth = COALESCE(EXCLUDED.date_of_birth, patients.date_of_birth),
                        contact = COALESCE(EXCLUDED.contact, patients.contact),
                        allergies = EXCLUDED.allergies,
                        chronic_conditions = EXCLUDED.chronic_conditions,
                        blood_type = COALESCE(EXCLUDED.blood_type, patients.blood_type),
                        updated_at = NOW()
                    """,
                    (
                        body.patient_id,
                        body.patient_id,
                        pp.name,
                        pp.gender,
                        pp.age,
                        pp.date_of_birth,
                        pp.contact,
                        Json(pp.allergies),
                        Json(pp.chronic_conditions),
                        pp.blood_type,
                        Json({}),
                    ),
                )
            cur.execute(
                """
                INSERT INTO admissions (
                    admission_id, encounter_id, patient_id, bed_id, admission_code, admit_time, discharge_time,
                    status, encounter_status, primary_diagnosis, admission_reason, severity_on_admission,
                    attending_team, scenario_tag
                ) VALUES (%s,%s,%s,%s,%s,%s,NULL,'active',%s,%s,%s,%s,%s,%s,%s)
                RETURNING admission_id, encounter_id, patient_id, bed_id, admission_code, admit_time, discharge_time,
                          status, encounter_status, primary_diagnosis, admission_reason, severity_on_admission,
                          attending_team, scenario_tag, created_at, updated_at
                """,
                (
                    body.admission_id,
                    body.encounter_id,
                    body.patient_id,
                    body.bed_id,
                    body.admission_code,
                    body.admit_time,
                    body.encounter_status,
                    body.primary_diagnosis,
                    body.admission_reason,
                    body.severity_on_admission,
                    body.attending_team,
                    body.scenario_tag,
                ),
            )
            row = cur.fetchone()
            cur.execute("UPDATE beds SET status = 'occupied', updated_at = NOW() WHERE bed_id = %s", (body.bed_id,))
            cur.execute(
                """
                INSERT INTO audit_logs (id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output)
                VALUES ('log_' || substr(md5(random()::text),1,12), NOW(), 'system', 'api', 'create_event', 'admission', %s, %s::jsonb, %s::jsonb)
                """,
                (body.admission_id, '{"action":"create_admission"}', '{"status":"active"}'),
            )
    out = AdmissionOut(**row)
    publish_contract_event(
        event_type="patient.admitted",
        patient_id=body.patient_id,
        encounter_id=body.encounter_id,
        data={
            "admission_id": body.admission_id,
            "bed_id": body.bed_id,
            "source": "POST /admissions",
        },
        durable=True,
    )
    if idempotency_key:
        store_response(conn, key=idempotency_key, route=route_key, inner_payload=out.model_dump(mode="json"))
    return out


@router.patch("/admissions/{admission_id}/status", response_model=AdmissionOut)
def update_admission_status(admission_id: str, body: AdmissionStatusUpdate, conn: Connection = Depends(get_db)) -> AdmissionOut:
    conn.row_factory = dict_row
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE admissions
                SET status = %s,
                    discharge_time = COALESCE(%s, discharge_time),
                    encounter_status = CASE
                        WHEN %s::text = 'discharged' THEN 'DISCHARGED'::text
                        WHEN %s::text = 'expired' THEN 'COMPLETED'::text
                        WHEN %s::text = 'transferred' THEN 'TRANSFERRING'::text
                        ELSE encounter_status
                    END,
                    updated_at = NOW()
                WHERE admission_id = %s
                RETURNING admission_id, encounter_id, patient_id, bed_id, admission_code, admit_time, discharge_time,
                          status, encounter_status, primary_diagnosis, admission_reason, severity_on_admission,
                          attending_team, scenario_tag, created_at, updated_at
                """,
                (body.status, body.discharge_time, body.status, body.status, body.status, admission_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail='admission not found')
            if body.status != 'active':
                cur.execute("UPDATE beds SET status = 'empty', updated_at = NOW() WHERE bed_id = %s", (row['bed_id'],))
    return AdmissionOut(**row)


@router.post("/encounters/{encounter_id}/transfer", response_model=TransferAcceptedData)
def post_encounter_transfer(
    encounter_id: str,
    body: TransferRequestBody,
    conn: Connection = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TransferAcceptedData:
    """§6.1 ICU receiver — allocates bed and creates admission."""
    if encounter_id != encounter_id.strip():
        _raise_id_malformed("encounter_id")
    if not _ENCOUNTER_ID_RE.match(encounter_id):
        _raise_id_malformed("encounter_id")
    if not _PATIENT_ID_RE.match(body.patient_id):
        _raise_id_malformed("patient_id")

    route_key = f"POST /api/v1/encounters/{encounter_id}/transfer"
    conn.row_factory = dict_row
    if idempotency_key:
        cached = get_cached_response(conn, key=idempotency_key, route=route_key)
        if cached:
            return TransferAcceptedData(**cached)

    if body.to_group != "groupC.icu":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "STATE_TRANSITION_INVALID",
                "message": "This ICU endpoint only accepts to_group=groupC.icu",
            },
        )

    transfer_id = new_transfer_id()
    admission_id = new_icu_admission_id()
    admit_time = datetime.now(timezone.utc)

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO patients (
                    patient_id, patient_code, name, gender, age, date_of_birth,
                    contact, allergies, chronic_conditions, blood_type, baseline_profile
                ) VALUES (%s,%s,%s,%s,%s,NULL,NULL,%s::jsonb,%s::jsonb,NULL,%s::jsonb)
                ON CONFLICT (patient_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    gender = EXCLUDED.gender,
                    age = EXCLUDED.age,
                    updated_at = NOW()
                """,
                (
                    body.patient_id,
                    body.patient_id,
                    body.patient_name,
                    body.patient_gender,
                    body.patient_age,
                    Json([]),
                    Json([]),
                    Json({}),
                ),
            )
            cur.execute(
                "SELECT bed_id FROM beds WHERE status = 'empty' ORDER BY bed_id LIMIT 1 FOR UPDATE SKIP LOCKED"
            )
            bed_row = cur.fetchone()
            if not bed_row:
                out = TransferAcceptedData(
                    transfer_id=transfer_id,
                    status="rejected",
                    assigned_bed=None,
                    expected_eta_minutes=None,
                )
                if idempotency_key:
                    store_response(conn, key=idempotency_key, route=route_key, inner_payload=out.model_dump(mode="json"))
                return out

            assigned_bed = bed_row["bed_id"]
            cur.execute(
                "UPDATE beds SET status = 'occupied', updated_at = NOW() WHERE bed_id = %s",
                (assigned_bed,),
            )
            cur.execute(
                """
                INSERT INTO admissions (
                    admission_id, encounter_id, patient_id, bed_id, admission_code, admit_time, discharge_time,
                    status, encounter_status, primary_diagnosis, admission_reason, severity_on_admission,
                    attending_team, scenario_tag
                ) VALUES (%s,%s,%s,%s,%s,%s,NULL,'active','ADMITTED',%s,%s,%s,%s,%s)
                RETURNING admission_id
                """,
                (
                    admission_id,
                    encounter_id,
                    body.patient_id,
                    assigned_bed,
                    admission_id,
                    admit_time,
                    ", ".join(body.summary.active_diagnoses) or "pending diagnosis",
                    body.reason,
                    "critical" if body.ctas_level in ("L1", "L2") else "unstable",
                    "Transfer intake",
                    "transfer_in",
                ),
            )
            cur.fetchone()
            cur.execute(
                """
                INSERT INTO patient_state_current (
                    admission_id, patient_id, bed_id, current_vitals, active_problems, active_risks,
                    latest_interventions, care_phase
                ) VALUES (%s,%s,%s,'{}'::jsonb,'[]'::jsonb,'[]'::jsonb,'[]'::jsonb,'critical')
                ON CONFLICT (admission_id) DO NOTHING
                """,
                (admission_id, body.patient_id, assigned_bed),
            )

    zone = {"L1": "red", "L2": "red", "L3": "yellow", "L4": "green", "L5": "green"}[body.ctas_level]
    xfer_payload: dict[str, Any] = {
        "transfer_id": transfer_id,
        "from_group": body.from_group,
        "to_group": body.to_group,
        "ctas_level": body.ctas_level,
        "zone": zone,
        "admission_id": admission_id,
        "assigned_bed": assigned_bed,
    }
    publish_contract_event(
        event_type="patient.transferred",
        patient_id=body.patient_id,
        encounter_id=encounter_id,
        data=xfer_payload,
        durable=True,
    )
    publish_contract_event(
        event_type="patient.admitted",
        patient_id=body.patient_id,
        encounter_id=encounter_id,
        data={
            "admission_id": admission_id,
            "bed_id": assigned_bed,
            "transfer_id": transfer_id,
            "source": "transfer",
        },
        durable=True,
    )

    out = TransferAcceptedData(
        transfer_id=transfer_id,
        status="accepted",
        assigned_bed=assigned_bed,
        expected_eta_minutes=5,
    )
    if idempotency_key:
        store_response(conn, key=idempotency_key, route=route_key, inner_payload=out.model_dump(mode="json"))
    return out


@router.get("/ops/db/tables", response_model=list[str])
def list_db_tables(conn: Connection = Depends(get_db)) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
            """
        )
        return [r[0] for r in cur.fetchall()]


@router.get("/ops/db/tables/{table_name}", response_model=TableRowPreview)
def get_table_preview(table_name: str, limit: int = 50, conn: Connection = Depends(get_db)) -> TableRowPreview:
    limit = max(1, min(limit, 200))
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail='table not found')

        cur.execute(SQL("SELECT COUNT(*) AS n FROM {}" ).format(Identifier(table_name)))
        total = int(cur.fetchone()['n'])
        cur.execute(SQL("SELECT * FROM {} ORDER BY 1 DESC LIMIT %s").format(Identifier(table_name)), (limit,))
        rows = [dict(r) for r in cur.fetchall()]
    return TableRowPreview(table_name=table_name, total_rows=total, rows=rows)
