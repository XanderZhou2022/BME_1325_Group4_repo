from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WardCoordinatorEvaluateRequest(BaseModel):
    top_k: int = Field(default=10, ge=1, le=50)


class WardBedPriority(BaseModel):
    admission_id: str
    patient_id: str
    bed_id: str
    care_phase: Literal["stable", "unstable", "critical"]
    priority_score: int
    reason: str


class WardCoordinatorEvaluateResponse(BaseModel):
    generated_at: datetime
    active_admission_count: int
    priority_queue: list[WardBedPriority]
    pending_actions: list[str]
    ward_load_indicator: str
    alert_storm_summary: dict[str, int]
