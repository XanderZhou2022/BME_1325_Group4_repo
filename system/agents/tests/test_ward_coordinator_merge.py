from __future__ import annotations

import os
import sys

SYSTEM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if SYSTEM_ROOT not in sys.path:
    sys.path.append(SYSTEM_ROOT)
API_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "api"))
if API_ROOT not in sys.path:
    sys.path.append(API_ROOT)

from agents.ward_coordinator.service import _topic_from_reason  # noqa: E402


def test_merge_topic_for_shock_reasons() -> None:
    assert _topic_from_reason("high persistent_shock_risk") == "shock_related_alerts"
    assert _topic_from_reason("persistent_hypotension worsening") == "shock_related_alerts"


def test_merge_topic_for_respiratory_and_aki() -> None:
    assert _topic_from_reason("resp worsening with low spo2") == "respiratory_related_alerts"
    assert _topic_from_reason("aki concern and creatinine rising") == "aki_related_alerts"
