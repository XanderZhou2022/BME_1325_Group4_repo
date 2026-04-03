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
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    time_window: str
    recommended_action: str


class RiskSentinelEvaluateRequest(BaseModel):
    admission_id: str


class RiskSentinelEvaluateResponse(BaseModel):
    admission_id: str
    risks: list[RiskImage]
    escalation_level: EscalationLevel
    generated_at: datetime

