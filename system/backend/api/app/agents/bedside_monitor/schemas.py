from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


AnalysisWindow = Literal["last_1h", "last_4h", "last_6h"]
UrgencyLevel = Literal["info", "warning", "critical"]


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


class BedsideAnalyzeRequest(BaseModel):
    admission_id: str
    analysis_window: AnalysisWindow = "last_4h"
    # If not provided, agent uses the latest vital timestamp in the DB as analysis_end.
    analysis_end: datetime | None = None
    urine_output_points: list[UrineOutputPoint] | None = None


class BedsideAnalyzeResponse(BaseModel):
    patient_id: str
    bed_id: str
    analysis_window: str
    current_status_summary: str
    abnormal_flags: list[str]
    trend_labels: list[str]
    evidence: list[dict[str, Any]]
    urgency_level: UrgencyLevel
    generated_at: datetime

