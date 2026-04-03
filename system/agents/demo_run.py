from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone


# Ensure `local/system` is import root so `agents.*` works even when run from elsewhere.
SYSTEM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SYSTEM_ROOT not in sys.path:
    sys.path.append(SYSTEM_ROOT)

from agents.bedside_monitor.examples import get_bedside_cases
from agents.bedside_monitor.rules import run_bedside_monitor
from agents.intervention_tracker.examples import get_intervention_cases
from agents.intervention_tracker.rules import run_intervention_tracker


def _dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, indent=2)


def demo_bedside_monitor() -> None:
    print("=== Bedside Monitor Agent Demo ===")
    cases = get_bedside_cases()
    for case_name, case in cases.items():
        vitals = case["vitals"]
        urine = case.get("urine_output_points")
        analysis_end = max([v.timestamp for v in vitals] + [u.timestamp for u in urine or []])
        result = run_bedside_monitor(vitals=vitals, urine_output_points=urine, analysis_end=analysis_end)
        print(f"\n--- case: {case_name} ---")
        print(_dumps(result))


def demo_intervention_tracker() -> None:
    print("=== Intervention Tracker Agent Demo ===")
    cases = get_intervention_cases()
    for case_name, case in cases.items():
        result = run_intervention_tracker(
            intervention_type=case["intervention_type"],
            intervention_time=case["intervention_time"],
            pre_vitals=case["pre_vitals"],
            post_vitals=case["post_vitals"],
            observation_window=case["observation_window"],
        )
        print(f"\n--- case: {case_name} ---")
        print(_dumps(result))


def main() -> None:
    print(f"Demo started: {datetime.now(timezone.utc).isoformat()}")
    demo_bedside_monitor()
    demo_intervention_tracker()
    print("\nDemo finished.")


if __name__ == "__main__":
    main()

