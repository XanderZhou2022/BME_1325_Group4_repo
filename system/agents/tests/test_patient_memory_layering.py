from __future__ import annotations

from datetime import datetime, timezone
import os
import sys

SYSTEM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if SYSTEM_ROOT not in sys.path:
    sys.path.append(SYSTEM_ROOT)
API_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "api"))
if API_ROOT not in sys.path:
    sys.path.append(API_ROOT)

from agents.patient_memory.schemas import (  # noqa: E402
    InterventionEvent,
    TemporalStateSummary,
)
from agents.patient_memory.service import _build_three_layer_memory  # noqa: E402


def test_build_three_layer_memory_with_important_events() -> None:
    summary = TemporalStateSummary(
        admission_id="adm1",
        window_hours=24,
        current_vitals={"mean_arterial_pressure": 62.0},
        trend_vectors={"mean_arterial_pressure": "worsening"},
        volatility_index={"mean_arterial_pressure": 0.2},
        latest_interventions=[
            InterventionEvent(
                id="int1",
                admission_id="adm1",
                timestamp=datetime.now(timezone.utc),
                intervention_type="fluid_bolus",
            )
        ],
        data_completeness_ratio=0.8,
        snapshot_generated_at=datetime.now(timezone.utc),
    )
    events = [
        {
            "source_event_id": "out1",
            "source_agent": "bedside_monitor",
            "event_type": "vital_summary",
            "event_summary": "persistent hypotension in last 30 min",
            "importance_level": "warning",
            "evidence": {},
        }
    ]
    short, mid, long, active_problems, unresolved, key_events, response_patterns = _build_three_layer_memory(
        admission_reason="septic shock",
        important_events=events,
        summary=summary,
    )
    assert short.key_events
    assert "persistent_hypotension" in active_problems
    assert unresolved
    assert long.icu_course_summary
    assert isinstance(response_patterns, list)
    assert key_events
