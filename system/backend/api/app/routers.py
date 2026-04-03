from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from psycopg.rows import dict_row

from app.db import get_db
from app.schemas import (
    AlertOut,
    AdmissionOut,
    AuditLogOut,
    BedOut,
    EventOut,
    EventWriteResult,
    InterventionEventCreate,
    InterventionEventOut,
    LabEventCreate,
    LabEventOut,
    PatientOut,
    PatientStateCurrentOut,
    PatientStateSnapshotOut,
    RiskAssessmentOut,
    VitalSignEventCreate,
    VitalSignEventOut,
)
from app.services.event_pipeline import (
    write_intervention,
    write_lab,
    write_vital_sign,
)

router = APIRouter(prefix="/api/v1")

# === Agent-layer: bedside-level, rule-driven modules ===
from app.agents.bedside_monitor.router import router as bedside_monitor_router
from app.agents.intervention_tracker.router import router as intervention_tracker_router

router.include_router(bedside_monitor_router)
router.include_router(intervention_tracker_router)


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
    return EventWriteResult(**write_vital_sign(conn, admission_id, body))


@router.post("/admissions/{admission_id}/events/lab", response_model=EventWriteResult)
def post_lab(
    admission_id: str,
    body: LabEventCreate,
    conn: Connection = Depends(get_db),
) -> EventWriteResult:
    return EventWriteResult(**write_lab(conn, admission_id, body))


@router.post(
    "/admissions/{admission_id}/events/intervention",
    response_model=EventWriteResult,
)
def post_intervention(
    admission_id: str,
    body: InterventionEventCreate,
    conn: Connection = Depends(get_db),
) -> EventWriteResult:
    return EventWriteResult(**write_intervention(conn, admission_id, body))


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
                   date_of_birth, baseline_profile, created_at, updated_at
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
            SELECT admission_id, patient_id, bed_id, admission_code,
                   admit_time, discharge_time, status, primary_diagnosis,
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
