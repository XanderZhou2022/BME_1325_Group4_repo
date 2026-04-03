from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


InterventionType = Literal["fluid", "vasopressor", "ventilator_change"]

ResponseAssessment = Literal[
    "responsive",
    "partially_responsive",
    "non_responsive",
    "deteriorating_despite_intervention",
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


class InterventionEvaluateResponse(BaseModel):
    patient_id: str
    bed_id: str
    intervention_type: InterventionType
    intervention_time: datetime
    observation_window: str
    response_assessment: ResponseAssessment
    target_metrics: dict[str, Any]
    before_after_comparison: dict[str, Any]
    evidence: list[dict[str, Any]]
    escalation_hint: str
    generated_at: datetime

