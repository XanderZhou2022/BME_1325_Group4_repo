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
from pathlib import Path
from typing import Any

import requests

BASE_URL = "http://localhost:8000/api/v1/demo/auto"
DEFAULT_TRACE_LOG = Path("logs/simulation_agent_trace.jsonl")


def _unwrap_contract_response(resp: requests.Response) -> Any:
    """§5.2: successful /api/v1 JSON is wrapped as {ok, data, error, trace_id}."""
    resp.raise_for_status()
    body = resp.json()
    if not isinstance(body, dict) or "ok" not in body:
        return body
    if not body.get("ok"):
        err = body.get("error") or {}
        code = err.get("code", "REQUEST_FAILED")
        msg = err.get("message", str(body))
        detail = f"{code}: {msg}"
        raise requests.HTTPError(detail, response=resp)
    return body.get("data")


class StepSimulationClient:
    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def reset(self) -> dict:
        resp = self.session.post(f"{self.base_url}/reset", timeout=20)
        return _unwrap_contract_response(resp)

    def state(self) -> dict:
        resp = self.session.get(f"{self.base_url}/state", timeout=20)
        return _unwrap_contract_response(resp)

    def next_step(self) -> dict:
        resp = self.session.post(f"{self.base_url}/next", timeout=30)
        return _unwrap_contract_response(resp)

    def timeline(self, limit: int = 20) -> dict:
        resp = self.session.get(f"{self.base_url}/timeline?limit={limit}", timeout=20)
        return _unwrap_contract_response(resp)


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
    risk = step.get("risk_change", {})
    if risk:
        before = (risk.get("before") or {}).get("highest_severity")
        after = (risk.get("after") or {}).get("highest_severity")
        changed = risk.get("changed")
        print(f"       risk={before} -> {after} changed={changed}")


def _short(value: Any, limit: int = 220) -> str:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _print_agent_trace(step: dict) -> None:
    trace = step.get("agent_workflow_trace") or []
    if not trace:
        print("       workflow=(no agent output trace for this step)")
        return
    print("       workflow:")
    for idx, item in enumerate(trace, start=1):
        knowledge = item.get("knowledge") or {}
        llm = item.get("llm") or {}
        judgment = item.get("judgment") or {}
        print(
            "         "
            f"{idx}. {item.get('agent_name')} "
            f"output={item.get('output_type')} "
            f"human_review={item.get('human_review_required')}"
        )
        card_ids = knowledge.get("retrieved_card_ids") or []
        print(f"            knowledge_cards={card_ids}")
        print(
            "            "
            f"llm_used={llm.get('llm_used')} "
            f"fallback_used={llm.get('fallback_used')} "
            f"audit_log_id={llm.get('audit_log_id')}"
        )
        if judgment:
            print(f"            judgment={_short(judgment)}")
        generated_text = (llm.get("generated_text_fields") or {})
        if generated_text:
            print(f"            llm_output={_short(generated_text)}")


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _append_markdown(path: Path, step: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    risk = step.get("risk_change") or {}
    before = (risk.get("before") or {}).get("highest_severity")
    after = (risk.get("after") or {}).get("highest_severity")
    lines = [
        f"## Step {step.get('step_index')} - {step.get('event_type')}",
        "",
        f"- Admission: `{step.get('admission_id')}`",
        f"- Time: `{step.get('sim_time_before')}` -> `{step.get('sim_time_after')}`",
        f"- Risk: `{before}` -> `{after}`, changed=`{risk.get('changed')}`",
        f"- DB effects: `{json.dumps(step.get('db_effects', {}), ensure_ascii=False)}`",
        "",
        "### Agent Workflow",
    ]
    trace = step.get("agent_workflow_trace") or []
    if not trace:
        lines.append("- No agent output trace for this step.")
    for item in trace:
        knowledge = item.get("knowledge") or {}
        llm = item.get("llm") or {}
        lines.extend(
            [
                f"- `{item.get('agent_name')}` / `{item.get('output_type')}`",
                f"  - Knowledge cards: `{knowledge.get('retrieved_card_ids') or []}`",
                f"  - LLM: used=`{llm.get('llm_used')}`, fallback=`{llm.get('fallback_used')}`, audit=`{llm.get('audit_log_id')}`",
                f"  - Judgment: `{_short(item.get('judgment') or {}, 500)}`",
            ]
        )
    lines.append("")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def run_steps(
    client: StepSimulationClient,
    steps: int,
    delay_s: float,
    *,
    verbose_trace: bool,
    jsonl_log: Path | None,
    markdown_log: Path | None,
) -> None:
    for _ in range(steps):
        out = client.next_step()
        _print_step(out)
        if verbose_trace:
            _print_agent_trace(out)
        if jsonl_log:
            _append_jsonl(jsonl_log, out.get("full_observability_log") or out)
            print(f"       log_jsonl={jsonl_log}")
        if markdown_log:
            _append_markdown(markdown_log, out)
            print(f"       log_md={markdown_log}")
        if delay_s > 0:
            time.sleep(delay_s)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run step-based ICU demo simulation.")
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help="Demo auto API base (default: %(default)s)",
    )
    parser.add_argument("--reset", action="store_true", help="Reset demo data before running")
    parser.add_argument("--steps", type=int, default=1, help="How many steps to run")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay seconds between steps")
    parser.add_argument("--show-timeline", action="store_true", help="Print latest timeline after running")
    parser.add_argument("--verbose-trace", action="store_true", help="Print per-agent knowledge/LLM/judgment trace")
    parser.add_argument("--no-log", action="store_true", help="Disable JSONL observability logging")
    parser.add_argument("--log-jsonl", type=Path, default=DEFAULT_TRACE_LOG, help="Path for full per-step JSONL logs")
    parser.add_argument("--log-md", type=Path, default=None, help="Optional readable Markdown trace log")
    args = parser.parse_args()

    client = StepSimulationClient(base_url=args.base_url)
    if args.reset:
        st = client.reset()
        print(f"[RESET] {datetime.now().isoformat()} demo state reset")
        _print_state(st)
    else:
        _print_state(client.state())

    run_steps(
        client,
        max(1, args.steps),
        max(0.0, args.delay),
        verbose_trace=args.verbose_trace,
        jsonl_log=None if args.no_log else args.log_jsonl,
        markdown_log=args.log_md,
    )
    _print_state(client.state())

    if args.show_timeline:
        tl = client.timeline(20)
        print("[TIMELINE]")
        print(json.dumps(tl, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
