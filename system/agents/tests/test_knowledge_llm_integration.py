from __future__ import annotations

import os
import sys

SYSTEM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if SYSTEM_ROOT not in sys.path:
    sys.path.append(SYSTEM_ROOT)
API_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "api"))
if API_ROOT not in sys.path:
    sys.path.append(API_ROOT)

from agents.clinical_summary.schemas import (  # noqa: E402
    ActiveRisk,
    ClinicalSummaryRequest,
    InterventionResponse,
    MemoryContext,
    VitalsSummary,
)
from agents.clinical_summary.service import enrich_summary_with_knowledge_and_llm, generate_summary  # noqa: E402
from agents.risk_sentinel.service import _calculate_risk_from_payloads, enrich_risks_with_knowledge_and_llm  # noqa: E402
from llm.safety import SAFETY_CHECK_ENABLED, validate_llm_medical_safety  # noqa: E402


def _risk_inputs():
    bedside = {
        "urgency_level": "critical",
        "abnormal_flags": ["persistent_hypotension"],
        "trend_labels": [{"metric": "mean_arterial_pressure", "trend": "decreasing"}],
    }
    intervention = {
        "response_label": "deteriorating_despite_intervention",
        "intervention_type": "fluid_bolus",
        "memory_context_for_risk": {"recent_trajectory": "worsening", "unresolved_issues": ["rising_lactate"]},
    }
    return bedside, intervention


def test_risk_sentinel_preserves_rule_based_risk() -> None:
    bedside, intervention = _risk_inputs()
    risks, _flags = _calculate_risk_from_payloads(bedside_payload=bedside, intervention_payload=intervention)
    enriched, meta = enrich_risks_with_knowledge_and_llm(
        patient_id="P-test",
        bed_id="B-ICU-01",
        risks=risks,
        bedside_payload=bedside,
        intervention_payload=intervention,
        memory_payload=intervention["memory_context_for_risk"],
        llm_enabled=False,
    )
    assert {r["risk_type"] for r in enriched} == {r["risk_type"] for r in risks}
    assert meta["fallback_used"] is True


def test_risk_sentinel_output_contains_knowledge_background() -> None:
    bedside, intervention = _risk_inputs()
    risks, _flags = _calculate_risk_from_payloads(bedside_payload=bedside, intervention_payload=intervention)
    enriched, _meta = enrich_risks_with_knowledge_and_llm(
        patient_id="P-test",
        bed_id="B-ICU-01",
        risks=risks,
        bedside_payload=bedside,
        intervention_payload=intervention,
        memory_payload=intervention["memory_context_for_risk"],
        llm_enabled=False,
    )
    assert any(r["knowledge_background"] for r in enriched)
    assert all(r["human_review_required"] is True for r in enriched)


def test_risk_sentinel_no_treatment_recommendation() -> None:
    if not SAFETY_CHECK_ENABLED:
        return
    ok, violations = validate_llm_medical_safety(
        "risk_sentinel_explanation",
        {"human_review_required": True, "risk_explanations": [{"human_review_required": True, "explanation": "start norepinephrine now"}]},
        ["treatment_recommendation"],
    )
    assert ok is False
    assert violations


def test_risk_sentinel_fallback_when_llm_disabled() -> None:
    bedside, intervention = _risk_inputs()
    risks, _flags = _calculate_risk_from_payloads(bedside_payload=bedside, intervention_payload=intervention)
    enriched, meta = enrich_risks_with_knowledge_and_llm(
        patient_id="P-test",
        bed_id="B-ICU-01",
        risks=risks,
        bedside_payload=bedside,
        intervention_payload=intervention,
        memory_payload={},
        llm_enabled=False,
    )
    assert meta["llm_used"] is False
    assert meta["fallback_used"] is True
    assert all(r["llm_explanation"] for r in enriched)


def _summary_request() -> ClinicalSummaryRequest:
    from datetime import datetime

    return ClinicalSummaryRequest(
        patient_id="P-test",
        bed_id="B-ICU-01",
        admission_id="ADM-test",
        vitals_summary=VitalsSummary(abnormal_flags=["persistent_hypotension"], trend_labels=["mean_arterial_pressure_decreasing"]),
        intervention_responses=[
            InterventionResponse(
                intervention_id="latest",
                intervention_type="fluid_bolus",
                intervention_time=datetime.utcnow(),
                response_assessment="non_responsive",
                target_metrics={},
                before_after_comparison={},
            )
        ],
        active_risks=[ActiveRisk(risk_type="persistent_shock_risk", confidence=0.8, evidence="persistent hypotension", urgency_level="warning")],
        memory_context=MemoryContext(admission_reason="ICU monitoring", unresolved_problems=["persistent_hypotension"], key_turning_points=["latest_window"]),
    )


def test_clinical_summary_uses_agent_outputs_only() -> None:
    req = _summary_request()
    summary = generate_summary(req, summary_type="24h_round_summary")
    enriched, _meta = enrich_summary_with_knowledge_and_llm(summary=summary, req=req, bedside_payload={}, intervention_payload={}, memory_payload={}, llm_enabled=False)
    text = " ".join(enriched.key_changes_24h + enriched.watch_items)
    assert "sepsis" not in text.lower()


def test_clinical_summary_contains_major_problems() -> None:
    req = _summary_request()
    summary = generate_summary(req, summary_type="24h_round_summary")
    enriched, _meta = enrich_summary_with_knowledge_and_llm(summary=summary, req=req, bedside_payload={}, intervention_payload={}, memory_payload={}, llm_enabled=False)
    assert enriched.major_problems
    assert enriched.key_changes_24h
    assert enriched.watch_items
    assert enriched.review_reminders


def test_clinical_summary_no_treatment_plan() -> None:
    if not SAFETY_CHECK_ENABLED:
        return
    ok, violations = validate_llm_medical_safety(
        "clinical_summary_24h_round_summary",
        {"human_review_required": True, "major_problems": [{"human_review_required": True, "recent_course": "treatment plan: give antibiotics"}]},
        ["new_treatment_plan"],
    )
    assert ok is False
    assert violations


def test_clinical_summary_fallback_when_llm_fails() -> None:
    req = _summary_request()
    summary = generate_summary(req, summary_type="24h_round_summary")
    enriched, meta = enrich_summary_with_knowledge_and_llm(summary=summary, req=req, bedside_payload={}, intervention_payload={}, memory_payload={}, llm_enabled=False)
    assert meta["llm_used"] is False
    assert meta["fallback_used"] is True
    assert enriched.human_review_required is True
