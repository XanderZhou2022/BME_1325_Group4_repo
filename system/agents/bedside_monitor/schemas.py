from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


AnalysisWindow = Literal["last_1h", "last_4h", "last_6h"]
UrgencyLevel = Literal["info", "warning", "critical"]
RunStatus = Literal["ok", "degraded"]


class UrineOutputPoint(BaseModel):
    timestamp: datetime
    # Convention for this simulation: urine_output_ml_per_hour.
    # If you later wire in real urine output with a different unit, adjust rules constants accordingly.
    urine_output_ml_per_hour: float = Field(ge=0)


class VitalPoint(BaseModel):
    timestamp: datetime
    heart_rate: int | None = None
    mean_arterial_pressure: float | None = None
    respiratory_rate: float | None = None
    temperature: float | None = None
    spo2: float | None = None
    gcs: int | None = None


class BedsideAnalyzeRequest(BaseModel):
    admission_id: str
    analysis_window: AnalysisWindow = "last_4h"
    # If not provided, agent uses the latest vital timestamp in the DB as analysis_end.
    analysis_end: datetime | None = None
    urine_output_points: list[UrineOutputPoint] | None = None


class TimeWindow(BaseModel):
    start: datetime
    end: datetime
    window_minutes: int
    trend_hours: int


class AbnormalFlag(BaseModel):
    type: str
    severity: Literal["warning", "critical"]
    metric: str
    value: float
    threshold: str
    duration_minutes: int


class TrendLabel(BaseModel):
    metric: str
    trend: Literal["increasing", "decreasing", "stable"]
    evidence: str


class BedsideAnalyzeResponse(BaseModel):
    schema_version: str = "bedside_monitor.v1"
    agent_name: str = "bedside_monitor"
    status: RunStatus = "ok"
    admission_id: str
    patient_id: str
    bed_id: str
    time_window: TimeWindow
    current_status_summary: str
    abnormal_flags: list[AbnormalFlag]
    trend_labels: list[TrendLabel]
    evidence: dict[str, Any]
    urgency_level: UrgencyLevel
    next_action_hint: str
    generated_at: datetime

