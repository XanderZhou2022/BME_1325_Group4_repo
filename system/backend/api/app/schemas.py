from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


EventSource = Literal["monitor", "lab", "nurse", "agent"]
EventPriority = Literal["low", "normal", "high", "critical"]
InterventionType = Literal["fluid", "vasopressor", "ventilator_change"]
AbnormalFlag = Literal["normal", "high", "low"]
CarePhase = Literal["stable", "unstable", "critical"]


# === Write-side schemas (events) ===


class VitalSignEventCreate(BaseModel):
    timestamp: datetime
    source: EventSource = "monitor"
    priority: EventPriority = "normal"

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
    gender: Literal["male", "female", "other"]
    age: int
    date_of_birth: date | None = None
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
    patient_id: str
    bed_id: str
    admission_code: str
    admit_time: datetime
    discharge_time: datetime | None = None
    status: Literal["active", "discharged", "expired", "transferred"]
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
