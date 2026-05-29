from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, List, Dict

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
        "not_enough_data",
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
    status: Literal["active", "improving", "resolved", "unclear"] = "active"
    trajectory: Literal["improving", "stable", "worsening", "unclear"] = "unclear"
    supporting_evidence: List[str] = []
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class ClinicalSummaryResponse(BaseModel):
    """Output for Clinical Summary Agent."""
    schema_version: str = "clinical_summary.v1.1"
    agent: str = "clinical_summary"
    patient_id: str
    bed_id: str
    admission_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    summary_type: Literal["current_status_summary", "24h_round_summary"] = "current_status_summary"
    one_line_status: str = ""
    icu_course_context: str = ""
    last_24h_key_events: List[str] = []
    active_problem_list: List[Dict[str, Any]] = []
    key_interventions_and_responses: List[Dict[str, Any]] = []
    recommended_attention_targets: List[str] = []
    uncertainties_or_missing_data: List[str] = []
    urgency_level: Literal["info", "warning", "critical"] = "info"
    notify_agents: List[str] = []

    # backward-compatible fields
    twenty_four_hour_summary: str = Field(alias="24h_rounds_summary")
    problem_list: List[ProblemListItem] = []
    focus_areas_for_today: List[str] = []
    clinical_narrative: str
    major_problems: List[Dict[str, Any]] = []
    key_changes_24h: List[str] = []
    active_risks: List[str] = []
    watch_items: List[str] = []
    review_reminders: List[str] = []
    clinician_review_next_steps: List[str] = []
    forbidden_use_reminder: List[str] = []
    knowledge_context: List[Dict[str, Any]] = []
    llm_used: bool = False
    fallback_used: bool = True
    audit_log_id: str | None = None
    human_review_required: bool = True

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
