from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

SYSTEM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if SYSTEM_ROOT not in sys.path:
    sys.path.append(SYSTEM_ROOT)
API_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "api"))
if API_ROOT not in sys.path:
    sys.path.append(API_ROOT)

from agents.clinical_summary.schemas import ActiveRisk, InterventionResponse, VitalsSummary  # noqa: E402
from agents.clinical_summary.templates import build_problem_items, deduce_problems  # noqa: E402


def test_problem_list_contains_status_trajectory() -> None:
    problems = deduce_problems(
        vitals_summary=VitalsSummary(abnormal_flags=["persistent_hypotension"], trend_labels=["MAP_downtrend"], evidence=[]),
        active_risks=[ActiveRisk(risk_type="persistent_shock_risk", confidence=0.8, evidence="e", urgency_level="critical")],
        intervention_responses=[
            InterventionResponse(
                intervention_id="i1",
                intervention_type="fluid_bolus",
                intervention_time=datetime.now(timezone.utc),
                response_assessment="non_responsive",
                target_metrics={},
                before_after_comparison={},
            )
        ],
    )
    assert problems
    structured = build_problem_items(problems)
    assert "status" in structured[0]
    assert "trajectory" in structured[0]
