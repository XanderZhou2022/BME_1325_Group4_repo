from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


Urgency = Literal["info", "warning", "critical"]
SourceAgent = Literal["bedside_monitor", "intervention_tracker"]


class SharedBoardEntry(BaseModel):
    patient_id: str
    bed_id: str
    timestamp: datetime
    source_agent: SourceAgent
    summary: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    urgency: Urgency
    structured_payload: dict[str, Any] = Field(default_factory=dict)

