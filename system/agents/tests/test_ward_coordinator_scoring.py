from __future__ import annotations

import os
import sys

SYSTEM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if SYSTEM_ROOT not in sys.path:
    sys.path.append(SYSTEM_ROOT)
API_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "api"))
if API_ROOT not in sys.path:
    sys.path.append(API_ROOT)

from agents.ward_coordinator.service import _compute_priority_score, _priority_level  # noqa: E402


def test_priority_level_mapping() -> None:
    assert _priority_level(2) == "routine"
    assert _priority_level(4) == "watch"
    assert _priority_level(7) == "urgent"
    assert _priority_level(10) == "immediate"


def test_scoring_with_new_deterioration_and_non_response() -> None:
    score, reasons = _compute_priority_score(
        overall_risk="high",
        active_risk_count=2,
        trajectory="worsening",
        is_new_deterioration=True,
        response_label="non_responsive",
        has_unresolved_critical_issue=True,
    )
    assert score >= 11
    assert any("new deterioration" in r for r in reasons)
    assert any("non-responsive" in r for r in reasons)
