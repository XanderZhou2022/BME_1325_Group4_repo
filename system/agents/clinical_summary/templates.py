"""
Templates and Logic for Clinical Summary Agent.
Aggregates inputs from downstream agents into clinical summaries.
"""
from __future__ import annotations

from typing import List

from .schemas import (
    VitalsSummary,
    InterventionResponse,
    ActiveRisk,
    ProblemListItem,
)

# --- Logic Rules ---

# Flags from Bedside Monitor
MAP_HYPOTENSION_FLAG = "persistent_hypotension"
SPO2_HYPOXEMIA_FLAG = "hypoxemia"
HR_TACHYCARDIA_FLAG = "tachycardia"
OLIGURIA_FLAG = "oliguria"

# Risks from Risk Sentinel (hypothetical keys based on task book)
SHOCK_RISK_KEY = "shock_risk"
RESP_FAILURE_RISK_KEY = "respiratory_failure_risk"
SEPSIS_RISK_KEY = "sepsis_risk"


def deduce_problems(
    vitals_summary: VitalsSummary,
    active_risks: List[ActiveRisk],
    intervention_responses: List[InterventionResponse],
) -> List[ProblemListItem]:
    """
    Deduces and aggregates clinical problems from vital signs, risks, and interventions.
    """
    problems: List[ProblemListItem] = []

    # --- 1. Hemodynamic Stability ---
    has_hypotension = MAP_HYPOTENSION_FLAG in vitals_summary.abnormal_flags
    has_shock = any(r.risk_type.lower().startswith("shock") for r in active_risks)
    has_tachycardia = HR_TACHYCARDIA_FLAG in vitals_summary.abnormal_flags

    if has_hypotension or has_shock or has_tachycardia:
        # Determine intervention status
        status = "monitoring"
        relevant_interventions = [
            ir
            for ir in intervention_responses
            if ir.intervention_type in ["fluid", "vasopressor"]
        ]
        
        if relevant_interventions:
            latest = relevant_interventions[-1]
            if latest.response_assessment == "deteriorating_despite_intervention":
                status = "deteriorating"
            elif latest.response_assessment == "non_responsive":
                status = "non_responsive"
            elif latest.response_assessment in ["responsive", "partially_responsive"]:
                status = latest.response_assessment

        # Determine urgency
        urgency = "warning"
        if has_shock:
            urgency = "critical"
        if status == "deteriorating":
            urgency = "critical"

        # Evidence construction
        evidence_parts = []
        if has_hypotension:
            evidence_parts.append("Persistent hypotension")
        if has_shock:
            evidence_parts.append("High shock risk")
        if relevant_interventions:
            evidence_parts.append(f"Post-{relevant_interventions[-1].intervention_type}: {relevant_interventions[-1].response_assessment}")

        problems.append(
            ProblemListItem(
                problem="Hemodynamic Instability",
                urgency=urgency,
                evidence=", ".join(evidence_parts),
                intervention_status=status,
            )
        )

    # --- 2. Respiratory Stability ---
    has_hypoxemia = SPO2_HYPOXEMIA_FLAG in vitals_summary.abnormal_flags
    has_resp_failure = any(r.risk_type.lower().startswith("resp") for r in active_risks)

    if has_hypoxemia or has_resp_failure:
        status = "monitoring"
        relevant_interventions = [
            ir
            for ir in intervention_responses
            if ir.intervention_type == "ventilator_change"
        ]

        if relevant_interventions:
            latest = relevant_interventions[-1]
            if latest.response_assessment in [
                "responsive",
                "partially_responsive",
                "non_responsive",
            ]:
                status = latest.response_assessment
            elif latest.response_assessment == "deteriorating_despite_intervention":
                status = "deteriorating"

        urgency = "warning"
        if status == "deteriorating":
            urgency = "critical"

        evidence_parts = []
        if has_hypoxemia:
            evidence_parts.append("Hypoxemia detected")
        if relevant_interventions:
            evidence_parts.append(f"Post-ventilation change: {relevant_interventions[-1].response_assessment}")

        problems.append(
            ProblemListItem(
                problem="Respiratory Instability",
                urgency=urgency,
                evidence=", ".join(evidence_parts),
                intervention_status=status,
            )
        )

    # --- 3. Renal Function (Oliguria) ---
    if OLIGURIA_FLAG in vitals_summary.abnormal_flags:
        problems.append(
            ProblemListItem(
                problem="Renal Concern (Oliguria)",
                urgency="warning",
                evidence="Decreased urine output",
                intervention_status="monitoring",
            )
        )

    # --- 4. Sorting ---
    # Critical > Warning > Info
    # Deteriorating > Non-responsive > Responsive
    urgency_order = {"critical": 0, "warning": 1, "info": 2}
    status_order = {
        "deteriorating": 0,
        "non_responsive": 1,
        "monitoring": 2,
        "partially_responsive": 3,
        "responsive": 4,
    }
    
    problems.sort(
        key=lambda p: (
            urgency_order.get(p.urgency, 3),
            status_order.get(p.intervention_status, 5),
        )
    )

    return problems


def generate_summary_text(
    admission_reason: str,
    problems: List[ProblemListItem],
    interventions: List[InterventionResponse],
    unresolved_problems: List[str],
) -> str:
    """Generates the 24h round summary and narrative."""
    
    if not problems:
        return f"Patient admitted for: {admission_reason}. Currently stable with no active alerts."

    primary_issue = problems[0].problem
    secondary_issues = [p.problem for p in problems[1:]] if len(problems) > 1 else []

    text_parts = []
    text_parts.append(f"Admitted for: {admission_reason}.")

    if secondary_issues:
        text_parts.append(
            f"Primary concern: {primary_issue}. Secondary concerns: {', '.join(secondary_issues)}."
        )
    else:
        text_parts.append(f"Primary concern: {primary_issue}.")

    # Mention intervention response
    if interventions:
        latest_int = interventions[-1]
        text_parts.append(
            f"Latest intervention ({latest_int.intervention_type}): {latest_int.response_assessment}."
        )

    if unresolved_problems:
        text_parts.append(f"Unresolved issues: {', '.join(unresolved_problems)}.")

    return " ".join(text_parts)


def generate_focus_areas(
    problems: List[ProblemListItem],
    interventions: List[InterventionResponse],
) -> List[str]:
    """Suggests focus areas based on active problems."""
    focus = []
    
    # Add focus for critical/warning problems
    for p in problems:
        if p.urgency in ["critical", "warning"]:
            if p.intervention_status in ["deteriorating", "non_responsive"]:
                focus.append(f"Re-evaluate management for: {p.problem}")
            else:
                focus.append(f"Monitor trend of: {p.problem}")
    
    # Suggest specific follow-ups based on interventions
    for ir in interventions:
        if ir.intervention_type == "fluid" and ir.response_assessment in ["non_responsive", "deteriorating"]:
            focus.append("Consider vasopressor initiation/escalation if not already on.")
        if ir.intervention_type == "ventilator_change":
            focus.append("Check ABG after ventilator adjustment.")
            
    if not focus:
        focus.append("Continue routine monitoring and care.")
        
    return focus