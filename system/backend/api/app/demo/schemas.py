from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


DemoEventType = Literal["admission_create", "admission_discharge", "vital_sign", "lab", "intervention"]


class DemoHospitalState(BaseModel):
    sim_time: datetime
    step_index: int
    active_admissions: int
    occupied_beds: int
    total_patients: int
    recent_events: list[dict[str, Any]] = []


class DemoDbEffects(BaseModel):
    agent_outputs_added: int = 0
    agent_events_added: int = 0
    alerts_added: int = 0
    risks_added: int = 0


class DemoNextResponse(BaseModel):
    step_index: int
    sim_time_before: datetime
    sim_time_after: datetime
    event_type: DemoEventType
    admission_id: str | None = None
    event_request_payload: dict[str, Any] = {}
    event_write_result: dict[str, Any] = {}
    triggered_agents: list[dict[str, Any]] = []
    db_effects: DemoDbEffects
    agent_delta_summary: dict[str, Any] = {}


class DemoTimelineItem(BaseModel):
    id: str
    step_index: int
    sim_time: datetime
    event_type: DemoEventType
    admission_id: str | None = None
    payload: dict[str, Any] = {}
    result: dict[str, Any] = {}
    created_at: datetime


class DemoTimelineResponse(BaseModel):
    items: list[DemoTimelineItem]
    total: int = Field(ge=0)
