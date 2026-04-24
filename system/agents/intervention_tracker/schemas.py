from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


InterventionType = Literal[
    "fluid",
    "vasopressor",
    "ventilator_change",
    "fluid_bolus",
    "vasopressor_adjustment",
    "ventilator_adjustment",
    "antibiotic_start",
]

ResponseAssessment = Literal[
    "responsive",
    "partially_responsive",
    "non_responsive",
    "deteriorating_despite_intervention",
    "pending_insufficient_data",
    "not_enough_data",
]


class PrePostWindow(BaseModel):
    pre_window_minutes: int = Field(ge=1, le=12 * 60, default=60)
    post_window_minutes: int = Field(ge=1, le=12 * 60, default=60)


class InterventionEvaluateRequest(BaseModel):
    admission_id: str
    intervention_id: str
    expected_observation_window_minutes: int | None = Field(default=None, ge=1, le=12 * 60)
    pre_window_minutes: int | None = Field(default=None, ge=1, le=12 * 60)
    post_window_minutes: int | None = Field(default=None, ge=1, le=12 * 60)


class VitalPoint(BaseModel):
    timestamp: datetime
    mean_arterial_pressure: float | None = None  # for fluid/vasopressor
    spo2: float | None = None  # for ventilator change
    respiratory_rate: float | None = None  # for ventilator change
    heart_rate: float | None = None
    temperature: float | None = None
    fio2: float | None = None
    peep: float | None = None
    lactate: float | None = None
    wbc: float | None = None


class AssessmentWindow(BaseModel):
    pre_window: str
    post_window: str


class MetricChange(BaseModel):
    metric: str
    before: str
    after: str
    interpretation: str


class InterventionEvaluateResponse(BaseModel):
    schema_version: str = "intervention_tracker.v1.1"
    agent: str = "intervention_tracker"
    admission_id: str
    patient_id: str
    bed_id: str
    intervention_id: str
    intervention_type: InterventionType
    intervention_time: datetime
    assessment_window: AssessmentWindow
    response_label: ResponseAssessment
    response_summary: str
    key_changes: list[MetricChange]
    concern_flags: list[str]
    urgency_level: Literal["info", "warning", "critical"]
    notify_agents: list[str]

    # Backward-compatible fields (do not remove yet)
    observation_window: str
    response_assessment: ResponseAssessment
    target_metrics: dict[str, Any]
    before_after_comparison: dict[str, Any]
    evidence: list[dict[str, Any]]
    escalation_hint: str
    generated_at: datetime

