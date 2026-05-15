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

from app.demo.schemas import DemoTimelineItem  # noqa: E402


def test_timeline_accepts_batch_step_event_type() -> None:
    """demo_auto_timeline rows now use event_type=batch_step for ward ticks."""
    now = datetime.now(timezone.utc)
    row = DemoTimelineItem(
        id="dtl_test",
        step_index=1,
        sim_time=now,
        event_type="batch_step",
        admission_id=None,
        payload={"sub_events": []},
        result={},
        created_at=now,
    )
    assert row.event_type == "batch_step"
