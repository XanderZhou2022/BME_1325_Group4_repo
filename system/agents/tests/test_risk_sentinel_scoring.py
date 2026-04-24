from __future__ import annotations

import os
import sys

SYSTEM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if SYSTEM_ROOT not in sys.path:
    sys.path.append(SYSTEM_ROOT)
API_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "api"))
if API_ROOT not in sys.path:
    sys.path.append(API_ROOT)

from agents.risk_sentinel.service import _calculate_risk_from_payloads  # noqa: E402


def test_shock_risk_worsening_detected() -> None:
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
    risks, flags = _calculate_risk_from_payloads(bedside_payload=bedside, intervention_payload=intervention)
    assert any(r["risk_type"] == "persistent_shock_risk" for r in risks)
    assert "shock_risk_worsening" in flags


def test_aki_risk_from_oliguria_signal() -> None:
    bedside = {"urgency_level": "warning", "abnormal_flags": ["oliguria"], "trend_labels": []}
    intervention = {"response_label": "non_responsive", "intervention_type": "fluid_bolus", "memory_context_for_risk": {"unresolved_issues": ["creatinine_rising"]}}
    risks, _flags = _calculate_risk_from_payloads(bedside_payload=bedside, intervention_payload=intervention)
    assert any(r["risk_type"] == "aki_risk" for r in risks)
