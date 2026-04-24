from __future__ import annotations

import os
import sys

SYSTEM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if SYSTEM_ROOT not in sys.path:
    sys.path.append(SYSTEM_ROOT)
API_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "api"))
if API_ROOT not in sys.path:
    sys.path.append(API_ROOT)

import app.demo.service as demo_service  # noqa: E402


def test_choose_event_type_with_no_active_admissions() -> None:
    assert demo_service._choose_event_type(0) == "admission_create"


def test_choose_event_type_probability_buckets() -> None:
    old_random = demo_service.random.random
    try:
        demo_service.random.random = lambda: 0.10
        assert demo_service._choose_event_type(5) == "admission_create"
        demo_service.random.random = lambda: 0.25
        assert demo_service._choose_event_type(5) == "admission_discharge"
        demo_service.random.random = lambda: 0.45
        assert demo_service._choose_event_type(5) == "vital_sign"
        demo_service.random.random = lambda: 0.70
        assert demo_service._choose_event_type(5) == "intervention"
        demo_service.random.random = lambda: 0.92
        assert demo_service._choose_event_type(5) == "lab"
    finally:
        demo_service.random.random = old_random
