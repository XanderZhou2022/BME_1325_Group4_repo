from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


RiskSeverity = Literal["low", "warning", "critical"]
EscalationLevel = Literal["info", "warning", "critical"]


class RiskImage(BaseModel):
    risk_type: str
    confidence: Decimal = Field(ge=0, le=1)
    severity: RiskSeverity
    evidence: list[dict[str, Any]]
    time_window: str
    recommended_action: str


class RiskSentinelEvaluateRequest(BaseModel):
    admission_id: str
    max_events: int = Field(default=200, ge=1, le=2000)
    force_recompute: bool = False


class RiskSentinelEvaluateResponse(BaseModel):
    admission_id: str
    consumed_event_count: int
    consumed_event_ids: list[str]
    risks: list[RiskImage]
    escalation_level: EscalationLevel
    generated_at: datetime