from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DemoRunRequest(BaseModel):
    admission_id: str | None = None
    run_all_active: bool = False
    memory_window_hours: int = Field(default=24, ge=1, le=72)
    top_k: int = Field(default=10, ge=1, le=50)


class StepResult(BaseModel):
    step_name: str
    admission_id: str
    status: Literal["ok", "skipped", "error"]
    started_at: datetime
    finished_at: datetime
    detail: dict
    input_sources: list[str] = []
    input_window: str | None = None
    output_id: str | None = None
    error_class: str | None = None
    retry_count: int = 0


class DemoRunResponse(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime
    target_admissions: list[str]
    step_results: list[StepResult]
