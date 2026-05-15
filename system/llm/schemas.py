from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RiskExplanationItem(BaseModel):
    risk_type: str
    risk_level: str
    explanation: str
    escalation_rationale: str
    supporting_card_ids: list[str]
    forbidden_use_reminder: list[str]
    human_review_required: bool


class RiskSentinelLLMOutput(BaseModel):
    patient_id: str
    time_window: str
    risk_explanations: list[RiskExplanationItem]
    overall_review_reminder: str
    human_review_required: bool


class MajorProblemItem(BaseModel):
    problem_name: str
    recent_course: str
    supporting_evidence: list[str]
    related_risks: list[str]
    intervention_response: str | None = None
    knowledge_context_card_ids: list[str]
    human_review_required: bool


class ClinicalSummaryLLMOutput(BaseModel):
    patient_id: str
    summary_type: str
    time_window: str
    major_problems: list[MajorProblemItem]
    key_changes_24h: list[str]
    active_risks: list[str]
    watch_items: list[str]
    review_reminders: list[str]
    forbidden_use_reminder: list[str]
    human_review_required: bool


class PatientMemoryNarrativeOutput(BaseModel):
    patient_id: str
    time_window: str
    short_term_narrative: str
    key_events: list[str]
    unresolved_issues: list[str]
    intervention_response_memory: list[str]
    communication_relevant_context: list[str]
    supporting_card_ids: list[str]
    forbidden_use_reminder: list[str]
    human_review_required: bool


class WardPriorityRationaleItem(BaseModel):
    bed_id: str
    priority_rank: int
    rule_based_priority_score: float
    rationale: str
    supporting_risk_types: list[str]
    supporting_card_ids: list[str]
    human_review_required: bool


class WardCoordinatorLLMOutput(BaseModel):
    ward_id: str
    generated_at: str
    priority_rationales: list[WardPriorityRationaleItem]
    global_watch_items: list[str]
    review_reminders: list[str]
    forbidden_use_reminder: list[str]
    human_review_required: bool


class FamilyCommunicationDraftOutput(BaseModel):
    patient_id: str
    draft_type: str
    clinician_review_version: str
    family_plain_language_draft: str
    icu_diary_draft: str | None = None
    communication_cautions: list[str]
    what_not_to_say: list[str]
    supporting_card_ids: list[str]
    forbidden_use_reminder: list[str]
    requires_clinician_approval_before_delivery: bool
    human_review_required: bool


class BedsideKnowledgeContext(BaseModel):
    abnormal_signal: str
    trend_label: str
    knowledge_background: list[dict]
    explanation: str
    forbidden_use_reminder: list[str]
    human_review_required: bool


class InterventionKnowledgeContext(BaseModel):
    intervention_type: str
    response_label: str
    knowledge_background: list[dict]
    explanation: str
    forbidden_use_reminder: list[str]
    human_review_required: bool


def model_to_plain_dict(model: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(model, BaseModel):
        return model.model_dump(mode="json")
    return model
