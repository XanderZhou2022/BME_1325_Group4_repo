from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


RiskSeverity = Literal["low", "moderate", "high", "critical"]
EscalationLevel = Literal["info", "watch", "urgent_review", "immediate_review"]


class RiskImage(BaseModel):
    risk_type: str
    confidence: Decimal = Field(ge=0, le=1)
    severity: RiskSeverity  # backward-compatible alias for risk_level
    risk_level: RiskSeverity
    evidence: list[dict[str, Any]]
    time_window: str
    recommended_action: str
    trajectory: Literal["improving", "stable", "worsening", "unclear"] = "unclear"
    escalation_level: EscalationLevel = "watch"


class RiskSentinelEvaluateRequest(BaseModel):
    admission_id: str
    max_events: int = Field(default=200, ge=1, le=2000)
    force_recompute: bool = False


class RiskSentinelEvaluateResponse(BaseModel):
    schema_version: str = "risk_sentinel.v1.1"
    agent: str = "risk_sentinel"
    admission_id: str
    patient_id: str
    bed_id: str
    overall_risk_level: RiskSeverity
    active_risks: list[RiskImage]
    new_or_worsening_flags: list[str]
    recommended_next_attention: list[str]
    notify_agents: list[str]
    consumed_event_count: int
    consumed_event_ids: list[str]
    # backward-compatible fields
    risks: list[RiskImage]
    escalation_level: EscalationLevel
    generated_at: datetime