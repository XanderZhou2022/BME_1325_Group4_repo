from __future__ import annotations

from datetime import datetime, timezone
import os
import sys

SYSTEM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if SYSTEM_ROOT not in sys.path:
    sys.path.append(SYSTEM_ROOT)

from agents.intervention_tracker.rules import run_intervention_tracker
from agents.intervention_tracker.schemas import VitalPoint


def _vp(ts_min: int, **kwargs: float) -> VitalPoint:
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    return VitalPoint(timestamp=base.replace(minute=ts_min), **kwargs)


def test_fluid_bolus_partial_response() -> None:
    pre = [_vp(0, mean_arterial_pressure=60), _vp(10, mean_arterial_pressure=61)]
    post = [_vp(20, mean_arterial_pressure=63), _vp(30, mean_arterial_pressure=64)]
    out = run_intervention_tracker(
        intervention_type="fluid_bolus",
        intervention_time=_vp(15).timestamp,
        pre_vitals=pre,
        post_vitals=post,
        observation_window="pre 30m / post 60m",
    )
    assert out["response_label"] in ("partially_responsive", "responsive")


def test_antibiotic_not_enough_data() -> None:
    out = run_intervention_tracker(
        intervention_type="antibiotic_start",
        intervention_time=_vp(15).timestamp,
        pre_vitals=[],
        post_vitals=[],
        observation_window="pre 360m / post 1440m",
    )
    assert out["response_label"] == "not_enough_data"
