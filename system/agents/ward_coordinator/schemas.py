from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class WardCoordinatorEvaluateRequest(BaseModel):
    top_k: int = Field(default=10, ge=1, le=50)


class ICUStatus(BaseModel):
    occupied_beds: int = 0
    critical_patients: int = 0
    high_risk_patients: int = 0
    new_deteriorations: int = 0


class MergedAlertGroup(BaseModel):
    alert_group: str
    beds: list[str]
    count: int


class WardPriorityItem(BaseModel):
    admission_id: str
    patient_id: str
    bed_id: str
    care_phase: Literal["stable", "unstable", "critical"]
    rank: int = 0
    priority_score: int
    priority_level: Literal["routine", "watch", "urgent", "immediate"] = "routine"
    reason: list[str] = []
    suggested_attention: str = "routine monitoring"
    source_risk_ids: list[str] = []
    source_event_ids: list[str] = []
    summary_hint: str = ""


class WardBedPriority(WardPriorityItem):
    """Backward-compatible alias."""


class WardCoordinatorEvaluateResponse(BaseModel):
    schema_version: str = "ward_coordinator.v1.1"
    agent: str = "ward_coordinator"
    generated_at: datetime
    active_admission_count: int
    icu_status: ICUStatus
    priority_queue: list[WardPriorityItem]
    merged_alerts: list[MergedAlertGroup] = []
    ward_summary: str = ""

    # backward-compatible fields
    pending_actions: list[str]
    ward_load_indicator: str
    alert_storm_summary: dict[str, int]
    debug_scoring: list[dict[str, Any]] = []
