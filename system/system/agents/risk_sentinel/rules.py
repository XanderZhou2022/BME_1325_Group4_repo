from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any


def _severity_to_confidence(severity: str) -> Decimal:
    # Keep mapping deterministic for tests/demo.
    if severity == "critical":
        return Decimal("0.92")
    if severity == "warning":
        return Decimal("0.80")
    return Decimal("0.65")


def _severity_to_escalation_level(severity: str) -> str:
    if severity == "critical":
        return "critical"
    if severity == "warning":
        return "warning"
    return "info"


def run_risk_sentinel(
    *,
    bedside_structured_payload: dict[str, Any] | None,
    bedside_evidence: list[dict[str, Any]] | None,
    intervention_structured_payload: dict[str, Any] | None,
    intervention_evidence: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    bedside_structured_payload = bedside_structured_payload or {}
    intervention_structured_payload = intervention_structured_payload or {}
    bedside_evidence = bedside_evidence or []
    intervention_evidence = intervention_evidence or []

    abnormal_flags: list[str] = list(bedside_structured_payload.get("abnormal_flags") or [])
    trend_labels: list[str] = list(bedside_structured_payload.get("trend_labels") or [])
    bedside_analysis_window: str = str(bedside_structured_payload.get("analysis_window") or "latest")

    intervention_type = str(intervention_structured_payload.get("intervention_type") or "")
    response_assessment = str(intervention_structured_payload.get("response_assessment") or "")
    before_after = intervention_structured_payload.get("before_after_comparison") or {}
    intervention_observation_window = str(intervention_structured_payload.get("observation_window") or "latest")

    # Normalize response category into "poor vs good".
    poor_response = response_assessment in ("non_responsive", "deteriorating_despite_intervention")
    partial_response = response_assessment == "partially_responsive"
    good_response = response_assessment == "responsive"

    risks: list[dict[str, Any]] = []

    # --- Risk 1: shock (seed name) ---
    # Trigger either from bedside persistent hypotension, or from a poor vasopressor response.
    shock_trigger = ("persistent_hypotension" in abnormal_flags) or (
        intervention_type == "vasopressor" and poor_response
    )
    if shock_trigger:
        if intervention_type == "vasopressor" and poor_response:
            severity = "critical"
        elif intervention_type == "vasopressor" and partial_response:
            severity = "warning"
        elif intervention_type in ("fluid", "vasopressor") and poor_response:
            severity = "critical"
        elif intervention_type in ("fluid", "vasopressor") and partial_response:
            severity = "warning"
        elif intervention_type in ("fluid", "vasopressor") and good_response:
            severity = "warning"
        else:
            severity = "warning"

        evidence = [
            {"source": "bedside", "evidence": bedside_evidence},
            {"source": "intervention", "response_assessment": response_assessment, "before_after": before_after},
            {"source": "bedside", "trend_labels": trend_labels},
        ]
        risks.append(
            {
                "risk_type": "shock",
                "severity": severity,
                "confidence": _severity_to_confidence(severity),
                "evidence": evidence,
                "time_window": bedside_analysis_window,
                "recommended_action": "review fluid response and source control",
            }
        )

    # --- Risk 2: respiratory failure (seed name) ---
    # Trigger either from bedside hypoxemia, or from a poor ventilator response.
    resp_trigger = ("hypoxemia" in abnormal_flags) or (
        intervention_type == "ventilator_change" and poor_response
    )
    if resp_trigger:
        if intervention_type == "ventilator_change" and poor_response:
            severity = "critical"
        elif intervention_type == "ventilator_change" and partial_response:
            severity = "warning"
        elif intervention_type == "ventilator_change" and good_response:
            severity = "low"
        else:
            severity = "warning"

        evidence = [
            {"source": "bedside", "evidence": bedside_evidence},
            {"source": "intervention", "response_assessment": response_assessment, "before_after": before_after},
            {"source": "bedside", "trend_labels": trend_labels},
        ]
        risks.append(
            {
                "risk_type": "respiratory_failure",
                "severity": severity,
                "confidence": _severity_to_confidence(severity),
                "evidence": evidence,
                "time_window": bedside_analysis_window,
                "recommended_action": "reassess ventilator settings and gas exchange",
            }
        )

    # --- Risk 3: persistent hypoperfusion (seed name) ---
    # Trigger from oliguria/persistent hypotension, or from poor fluid response.
    persistent_trigger = (
        "oliguria" in abnormal_flags
        or "persistent_hypotension" in abnormal_flags
        or (intervention_type == "fluid" and poor_response)
    )
    if persistent_trigger:
        if intervention_type == "fluid" and poor_response:
            severity = "critical"
        elif intervention_type == "fluid" and partial_response:
            severity = "warning"
        elif "oliguria" in abnormal_flags and poor_response:
            severity = "critical"
        elif "persistent_hypotension" in abnormal_flags:
            severity = "warning"
        else:
            severity = "warning"

        evidence = [
            {"source": "bedside", "evidence": bedside_evidence},
            {"source": "intervention", "response_assessment": response_assessment, "before_after": before_after},
        ]
        risks.append(
            {
                "risk_type": "persistent_hypoperfusion",
                "severity": severity,
                "confidence": _severity_to_confidence(severity),
                "evidence": evidence,
                "time_window": bedside_analysis_window,
                "recommended_action": "monitor post-fluid hemodynamic response",
            }
        )

    # De-duplicate by risk_type (if multiple triggers add same risk).
    uniq: dict[str, dict[str, Any]] = {}
    for r in risks:
        rt = str(r["risk_type"])
        # If duplicates, keep the highest severity.
        if rt not in uniq:
            uniq[rt] = r
        else:
            order = {"low": 0, "warning": 1, "critical": 2}
            if order[str(r["severity"])] > order[str(uniq[rt]["severity"])]:
                uniq[rt] = r

    risks = list(uniq.values())

    # Escalation level by highest severity.
    if not risks:
        escalation_level = "info"
    else:
        order = {"low": "info", "warning": "warning", "critical": "critical"}
        max_sev = max([str(r["severity"]) for r in risks], key=lambda s: {"low": 0, "warning": 1, "critical": 2}[s])
        escalation_level = order[max_sev]

    return {"risks": risks, "escalation_level": escalation_level}

