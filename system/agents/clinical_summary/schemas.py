from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional, List, Dict

from pydantic import BaseModel, Field


class VitalsSummary(BaseModel):
    """Summarized vital signs from Bedside Monitor."""
    abnormal_flags: List[str] = []
    trend_labels: List[str] = []
    evidence: List[Dict[str, Any]] = []


class InterventionResponse(BaseModel):
    """Response assessment from Intervention Tracker."""
    intervention_id: str
    intervention_type: str
    intervention_time: datetime
    response_assessment: Literal[
        "responsive",
        "partially_responsive",
        "non_responsive",
        "deteriorating_despite_intervention",
    ]
    target_metrics: Dict[str, Any] = {}
    before_after_comparison: Dict[str, Any] = {}


class ActiveRisk(BaseModel):
    """Risk assessment from Risk Sentinel."""
    risk_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str
    urgency_level: Literal["info", "warning", "critical"] = "info"


class MemoryContext(BaseModel):
    """Context from Patient Memory."""
    admission_reason: str
    major_icu_course: List[str] = []
    unresolved_problems: List[str] = []
    key_turning_points: List[str] = []


class ClinicalSummaryRequest(BaseModel):
    """Input for Clinical Summary Agent."""
    patient_id: str
    bed_id: str
    admission_id: str  # Link to database context if needed
    vitals_summary: VitalsSummary
    intervention_responses: List[InterventionResponse] = []
    active_risks: List[ActiveRisk] = []
    memory_context: MemoryContext


class ProblemListItem(BaseModel):
    problem: str
    urgency: Literal["info", "warning", "critical"]
    evidence: str
    intervention_status: str  # e.g., "responsive", "non_responsive", "monitoring"


class ClinicalSummaryResponse(BaseModel):
    """Output for Clinical Summary Agent."""
    patient_id: str
    bed_id: str
    admission_id: str
    generated_at: datetime = Field(default_factory=datetime.now)
    
    # 24h Rounds Summary
    twenty_four_hour_summary: str = Field(alias="24h_rounds_summary")
    
    # Problem List
    problem_list: List[ProblemListItem] = []
    
    # Focus Areas
    focus_areas_for_today: List[str] = []
    
    # Clinical Narrative
    clinical_narrative: str

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }