"""
Step-based auto demo simulation client.

This script now supports:
1) Reset demo hospital state
2) Move simulation one step at a time
3) Optional loop mode for N steps
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime

import requests

BASE_URL = "http://localhost:8000/api/v1/demo/auto"


class StepSimulationClient:
    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def reset(self) -> dict:
        resp = self.session.post(f"{self.base_url}/reset", timeout=20)
        resp.raise_for_status()
        return resp.json()

    def state(self) -> dict:
        resp = self.session.get(f"{self.base_url}/state", timeout=20)
        resp.raise_for_status()
        return resp.json()

    def next_step(self) -> dict:
        resp = self.session.post(f"{self.base_url}/next", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def timeline(self, limit: int = 20) -> dict:
        resp = self.session.get(f"{self.base_url}/timeline?limit={limit}", timeout=20)
        resp.raise_for_status()
        return resp.json()


def _print_state(state: dict) -> None:
    print(
        "[STATE] "
        f"time={state.get('sim_time')} "
        f"step={state.get('step_index')} "
        f"active={state.get('active_admissions')} "
        f"occupied={state.get('occupied_beds')} "
        f"patients={state.get('total_patients')}"
    )


def _print_step(step: dict) -> None:
    print(
        "[STEP] "
        f"#{step.get('step_index')} "
        f"{step.get('event_type')} "
        f"admission={step.get('admission_id')} "
        f"time {step.get('sim_time_before')} -> {step.get('sim_time_after')}"
    )
    print(f"       db_effects={json.dumps(step.get('db_effects', {}), ensure_ascii=False)}")
    delta = step.get("agent_delta_summary", {})
    print(f"       agents={delta.get('triggered_agent_names', [])}")


def run_steps(client: StepSimulationClient, steps: int, delay_s: float) -> None:
    for _ in range(steps):
        out = client.next_step()
        _print_step(out)
        if delay_s > 0:
            time.sleep(delay_s)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run step-based ICU demo simulation.")
    parser.add_argument("--reset", action="store_true", help="Reset demo data before running")
    parser.add_argument("--steps", type=int, default=1, help="How many steps to run")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay seconds between steps")
    parser.add_argument("--show-timeline", action="store_true", help="Print latest timeline after running")
    args = parser.parse_args()

    client = StepSimulationClient()
    if args.reset:
        st = client.reset()
        print(f"[RESET] {datetime.now().isoformat()} demo state reset")
        _print_state(st)
    else:
        _print_state(client.state())

    run_steps(client, max(1, args.steps), max(0.0, args.delay))
    _print_state(client.state())

    if args.show_timeline:
        tl = client.timeline(20)
        print("[TIMELINE]")
        print(json.dumps(tl, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()