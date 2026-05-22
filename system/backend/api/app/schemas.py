from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field


EventSource = Literal["monitor", "lab", "nurse", "agent"]
EventPriority = Literal["low", "normal", "high", "critical"]
InterventionType = Literal["fluid", "vasopressor", "ventilator_change"]
AbnormalFlag = Literal["normal", "high", "low"]
CarePhase = Literal["stable", "unstable", "critical"]

# Contract v1.0 §2 — global encounter-facing status (stored on admissions.encounter_status)
GlobalEncounterStatus = Literal[
    "ARRIVED",
    "REGISTERED",
    "TRIAGED",
    "IN_CONSULTATION",
    "IN_EXAM",
    "IN_TREATMENT",
    "ADMITTED",
    "DISCHARGED",
    "COMPLETED",
    "TRANSFERRING",
    "CANCELLED",
    "ERROR",
]


# === Write-side schemas (events) ===


class VitalSignEventCreate(BaseModel):
    timestamp: datetime
    source: EventSource = "monitor"
    priority: EventPriority = "normal"

    # Internal APACHE-style names; JSON may use contract VitalSigns names (§8 / appendix A.2)
    heart_rate: int | None = Field(None, validation_alias=AliasChoices("heart_rate", "hr"))
    mean_arterial_pressure: Decimal | None = Field(
        None, validation_alias=AliasChoices("mean_arterial_pressure", "map")
    )
    systolic_bp: Decimal | None = Field(None, validation_alias=AliasChoices("systolic_bp", "sbp"))
    diastolic_bp: Decimal | None = Field(None, validation_alias=AliasChoices("diastolic_bp", "dbp"))
    respiratory_rate: int | None = Field(None, validation_alias=AliasChoices("respiratory_rate", "rr"))
    temperature: Decimal | None = Field(None, validation_alias=AliasChoices("temperature", "temp"))
    spo2: Decimal | None = None
    fio2: Decimal | None = None
    pao2: Decimal | None = None
    aado2: Decimal | None = None
    ph: Decimal | None = None
    gcs: int | None = None


class LabEventCreate(BaseModel):
    timestamp: datetime
    lab_type: str = Field(min_length=1, max_length=128)
    value: Decimal
    unit: str = Field(min_length=1, max_length=64)
    abnormal_flag: AbnormalFlag
    source: EventSource = "lab"
    priority: EventPriority = "normal"


class InterventionEventCreate(BaseModel):
    timestamp: datetime
    intervention_type: InterventionType
    description: str = Field(min_length=1, max_length=2000)
    dosage: Decimal | None = None
    unit: str | None = Field(default=None, max_length=64)
    source: EventSource = "nurse"
    priority: EventPriority = "normal"


class EventWriteResult(BaseModel):
    event_id: str
    detail_id: str
    admission_id: str
    patient_id: str
    bed_id: str


# === Read-side schemas (state, alerts, risks) ===


class PatientStateCurrentOut(BaseModel):
    admission_id: str
    patient_id: str
    bed_id: str
    updated_at: datetime
    current_vitals: dict[str, Any]
    active_problems: list[Any]
    active_risks: list[Any]
    latest_interventions: list[Any]
    care_phase: CarePhase


class AlertOut(BaseModel):
    alert_id: str
    admission_id: str
    patient_id: str
    bed_id: str
    alert_type: str
    severity: Literal["info", "warning", "critical"]
    status: Literal["open", "acknowledged", "closed"]
    source_agent: str
    evidence: list[Any]
    first_seen_at: datetime
    last_seen_at: datetime


class RiskAssessmentOut(BaseModel):
    id: str
    admission_id: str
    timestamp: datetime
    risk_type: str
    confidence: Decimal
    severity: Literal["low", "warning", "critical"]
    evidence: list[Any]
    time_window: str
    recommended_action: str


# === Core entity schemas (for read APIs & debugging) ===


class PatientOut(BaseModel):
    patient_id: str
    patient_code: str
    name: str
    gender: Literal["male", "female", "other", "unknown"]
    age: int
    date_of_birth: date | None = None
    contact: str | None = None
    allergies: list[Any] = Field(default_factory=list)
    chronic_conditions: list[Any] = Field(default_factory=list)
    blood_type: str | None = None
    baseline_profile: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class BedOut(BaseModel):
    bed_id: str
    bed_code: str
    room_code: str
    bed_type: str
    status: Literal["occupied", "empty", "cleaning", "maintenance"]
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class AdmissionOut(BaseModel):
    admission_id: str
    encounter_id: str
    patient_id: str
    bed_id: str
    admission_code: str
    admit_time: datetime
    discharge_time: datetime | None = None
    status: Literal["active", "discharged", "expired", "transferred"]
    encounter_status: GlobalEncounterStatus
    primary_diagnosis: str
    admission_reason: str
    severity_on_admission: Literal["stable", "unstable", "critical"]
    attending_team: str
    scenario_tag: str
    created_at: datetime
    updated_at: datetime


class EventOut(BaseModel):
    event_id: str
    admission_id: str
    patient_id: str
    bed_id: str
    event_type: Literal["vital_sign", "lab", "intervention", "agent_output"]
    source: EventSource
    timestamp: datetime
    priority: EventPriority
    payload: dict[str, Any]


class VitalSignEventOut(BaseModel):
    id: str
    admission_id: str
    timestamp: datetime
    heart_rate: int | None = None
    mean_arterial_pressure: Decimal | None = None
    systolic_bp: Decimal | None = None
    diastolic_bp: Decimal | None = None
    respiratory_rate: int | None = None
    temperature: Decimal | None = None
    spo2: Decimal | None = None
    fio2: Decimal | None = None
    pao2: Decimal | None = None
    aado2: Decimal | None = None
    ph: Decimal | None = None
    gcs: int | None = None


class LabEventOut(BaseModel):
    id: str
    admission_id: str
    timestamp: datetime
    lab_type: str
    value: Decimal
    unit: str
    abnormal_flag: AbnormalFlag


class InterventionEventOut(BaseModel):
    id: str
    admission_id: str
    timestamp: datetime
    intervention_type: InterventionType
    description: str
    dosage: Decimal | None = None
    unit: str | None = None


class PatientStateSnapshotOut(BaseModel):
    id: str
    admission_id: str
    timestamp: datetime
    state_snapshot: dict[str, Any]


class AuditLogOut(BaseModel):
    id: str
    timestamp: datetime
    actor: Literal["agent", "system", "user"]
    actor_id: str
    action_type: Literal["create_event", "update_state", "run_agent"]
    target_type: str
    target_id: str
    input: dict[str, Any]
    output: dict[str, Any]


class AgentOutputOut(BaseModel):
    output_id: str
    admission_id: str
    patient_id: str
    bed_id: str
    agent_name: str
    schema_version: str
    output_type: str
    generated_at: datetime
    payload: dict[str, Any]


class AgentEventOut(BaseModel):
    event_id: str
    admission_id: str
    patient_id: str
    bed_id: str
    producer_agent: str
    event_type: str
    schema_version: str
    produced_at: datetime
    output_id: str | None = None
    payload: dict[str, Any]


class AgentCursorOut(BaseModel):
    consumer_agent: str
    admission_id: str
    last_event_id: str | None = None
    last_event_at: datetime | None = None
    updated_at: datetime


class DbHealthOut(BaseModel):
    status: Literal["ok", "error"]
    database: str
    server_time_utc: datetime | None = None

class AdmissionStatusUpdate(BaseModel):
    status: Literal["active", "discharged", "expired", "transferred"]
    discharge_time: datetime | None = None


class PatientProfileUpsert(BaseModel):
    """Optional: create/refresh patient row before admission (contract §8.4)."""

    name: str
    gender: Literal["male", "female", "other", "unknown"] = "unknown"
    age: int = 0
    date_of_birth: date | None = None
    contact: str | None = None
    allergies: list[Any] = Field(default_factory=list)
    chronic_conditions: list[Any] = Field(default_factory=list)
    blood_type: str | None = None


class AdmissionCreate(BaseModel):
    admission_id: str
    encounter_id: str
    patient_id: str
    bed_id: str
    admission_code: str
    admit_time: datetime
    primary_diagnosis: str
    admission_reason: str
    severity_on_admission: Literal["stable", "unstable", "critical"]
    attending_team: str
    scenario_tag: str = "custom"
    encounter_status: GlobalEncounterStatus = "ADMITTED"
    patient_profile: PatientProfileUpsert | None = None


class VitalBaselineIn(BaseModel):
    hr: int | None = None
    sbp: int | None = None
    dbp: int | None = None
    spo2: int | None = None
    temp: float | None = None
    rr: int | None = None


class TransferSummaryIn(BaseModel):
    chief_complaint: str = ""
    key_findings: list[str] = Field(default_factory=list)
    active_diagnoses: list[str] = Field(default_factory=list)
    active_orders: list[str] = Field(default_factory=list)
    vital_baseline: VitalBaselineIn = Field(default_factory=VitalBaselineIn)


class TransferRequestBody(BaseModel):
    """§6.1 cross-group transfer — extended with patient_id for ICU intake."""

    from_group: str
    to_group: str
    reason: str
    ctas_level: Literal["L1", "L2", "L3", "L4", "L5"]
    summary: TransferSummaryIn
    requested_resources: dict[str, Any] = Field(default_factory=dict)
    patient_id: str
    patient_name: str = "Unknown"
    patient_gender: Literal["male", "female", "other", "unknown"] = "unknown"
    patient_age: int = 0


class TransferAcceptedData(BaseModel):
    transfer_id: str
    status: Literal["accepted", "rejected", "pending"]
    assigned_bed: str | None = None
    expected_eta_minutes: int | None = None
    retry_after_seconds: int | None = None


class TableRowPreview(BaseModel):
    table_name: str
    total_rows: int
    rows: list[dict[str, Any]]


class MdtConsultationLimits(BaseModel):
    labs: int = Field(default=20, ge=1, le=100)
    interventions: int = Field(default=20, ge=1, le=100)
    risks: int = Field(default=10, ge=1, le=50)


class MdtConsultationTriggerIn(BaseModel):
    reason: str = "ICU manual MDT consultation"
    questions_for_mdt: list[str] = Field(default_factory=list)
    use_api: bool = False
    limits: MdtConsultationLimits = Field(default_factory=MdtConsultationLimits)


class MdtConsultationResultOut(BaseModel):
    admission_id: str
    patient_id: str
    consultation_id: str
    finalized: bool
    mdt_output_type: str
    mdt_judgment: dict[str, Any] = Field(default_factory=dict)
    treatment_and_surgical_plan: list[Any] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    required_updates: list[dict[str, Any]] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    case_summary: str = ""
    safety_boundary: str = ""
    output_id: str
    simi_health_ok: bool = True


class MdtLatestOut(BaseModel):
    output_id: str
    admission_id: str
    patient_id: str
    bed_id: str
    agent_name: str
    schema_version: str
    output_type: str
    generated_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
