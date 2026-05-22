from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.config import get_settings

from .audit import write_llm_audit
from .dashscope_config import chat_completions_url, load_api_test_env
from .safety import validate_llm_medical_safety

load_api_test_env()

T = TypeVar("T", bound=BaseModel)


@dataclass
class StructuredOutputResult:
    output: BaseModel
    llm_used: bool
    fallback_used: bool
    audit_log_id: str
    error: str | None = None


def _card_ids(input_payload: dict[str, Any]) -> list[str]:
    return [str(c.get("card_id")) for c in input_payload.get("retrieved_knowledge_cards", []) if isinstance(c, dict) and c.get("card_id")]


def _risk_fallback(input_payload: dict[str, Any]) -> dict[str, Any]:
    cards = _card_ids(input_payload)
    explanations = []
    for risk in input_payload.get("rule_based_risks", []):
        explanations.append(
            {
                "risk_type": str(risk.get("risk_type", "unknown_risk")),
                "risk_level": str(risk.get("risk_level", "low")),
                "explanation": "A rule-based risk pattern was detected. LLM explanation was unavailable. Clinician review is required.",
                "escalation_rationale": "The rule-triggered pattern should remain visible for clinical review. This is not a diagnosis or treatment recommendation.",
                "supporting_card_ids": cards[:3],
                "forbidden_use_reminder": [
                    "Do not use this output as a diagnosis.",
                    "Do not use this output as a treatment recommendation.",
                    "Clinician review is required.",
                ],
                "human_review_required": True,
            }
        )
    return {
        "patient_id": str(input_payload.get("patient_id", "")),
        "time_window": str(input_payload.get("time_window", "last_6h")),
        "risk_explanations": explanations,
        "overall_review_reminder": "Risk Sentinel outputs are decision-support signals only and require clinician review.",
        "human_review_required": True,
    }


def _summary_fallback(input_payload: dict[str, Any]) -> dict[str, Any]:
    cards = _card_ids(input_payload)
    risks = [str(r.get("risk_type")) for r in input_payload.get("risk_sentinel_summary", {}).get("active_risks", []) if isinstance(r, dict)]
    problems = []
    for risk in risks or ["structured agent outputs"]:
        problems.append(
            {
                "problem_name": f"Rule-based active risk: {risk}",
                "recent_course": "Clinical Summary used structured agent outputs. LLM summary generation was unavailable.",
                "supporting_evidence": ["See Bedside Monitor, Intervention Tracker, Risk Sentinel, and Patient Memory structured outputs."],
                "related_risks": risks,
                "intervention_response": None,
                "knowledge_context_card_ids": cards[:3],
                "human_review_required": True,
            }
        )
    return {
        "patient_id": str(input_payload.get("patient_id", "")),
        "summary_type": str(input_payload.get("summary_type", "24h_round_summary")),
        "time_window": str(input_payload.get("time_window", "last_24h")),
        "major_problems": problems,
        "key_changes_24h": ["Structured input was summarized with fallback logic."],
        "active_risks": risks,
        "watch_items": ["Clinician review required."],
        "review_reminders": ["This summary is generated from structured agent outputs and knowledge cards.", "It must be reviewed by clinical staff before use."],
        "forbidden_use_reminder": [
            "Do not use this summary as a diagnosis.",
            "Do not use this summary as a treatment plan.",
            "Do not communicate this directly to family without clinician review.",
        ],
        "human_review_required": True,
    }


def _memory_fallback(input_payload: dict[str, Any]) -> dict[str, Any]:
    cards = _card_ids(input_payload)
    events = input_payload.get("recent_events", [])
    key_events = [str(e.get("event_summary") or e.get("summary") or e) for e in events[:5] if isinstance(e, dict)]
    unresolved = [str(x) for x in input_payload.get("unresolved_issues", [])]
    return {
        "patient_id": str(input_payload.get("patient_id", "")),
        "time_window": str(input_payload.get("time_window", "last_24h")),
        "short_term_narrative": " ".join(key_events) if key_events else "No high-importance events were captured in the selected window.",
        "key_events": key_events,
        "unresolved_issues": unresolved,
        "intervention_response_memory": [str(x) for x in input_payload.get("response_patterns", [])],
        "communication_relevant_context": [],
        "supporting_card_ids": cards[:5],
        "forbidden_use_reminder": [
            "Do not use this memory narrative as a diagnosis.",
            "Do not use this memory narrative as a treatment recommendation.",
            "Clinician review is required.",
        ],
        "human_review_required": True,
    }


def _ward_fallback(input_payload: dict[str, Any]) -> dict[str, Any]:
    cards = _card_ids(input_payload)
    rationales = []
    for item in input_payload.get("priority_queue", []):
        if not isinstance(item, dict):
            continue
        rationales.append(
            {
                "bed_id": str(item.get("bed_id", "")),
                "priority_rank": int(item.get("priority_rank") or item.get("rank") or 0),
                "rule_based_priority_score": float(item.get("rule_based_priority_score") or item.get("priority_score") or 0),
                "rationale": "This position is based on structured rule scoring and requires clinician review.",
                "supporting_risk_types": [str(x) for x in item.get("active_risks", [])],
                "supporting_card_ids": cards[:5],
                "human_review_required": True,
            }
        )
    return {
        "ward_id": str(input_payload.get("ward_id", "icu_01")),
        "generated_at": str(input_payload.get("generated_at", "")),
        "priority_rationales": rationales,
        "global_watch_items": ["Review high-priority queue items using clinical judgment."],
        "review_reminders": ["Ward Coordinator explanations do not allocate beds or decide admission/discharge."],
        "forbidden_use_reminder": [
            "Do not use this queue as automatic bed allocation.",
            "Do not use this queue as ICU admission or discharge decision.",
        ],
        "human_review_required": True,
    }


def _family_fallback(input_payload: dict[str, Any]) -> dict[str, Any]:
    cards = _card_ids(input_payload)
    return {
        "patient_id": str(input_payload.get("patient_id", "")),
        "draft_type": str(input_payload.get("draft_type", "daily_family_update_draft")),
        "clinician_review_version": "Draft generated for clinician review only.",
        "family_plain_language_draft": "A clinician should review the latest ICU summary before any family update is shared.",
        "icu_diary_draft": "Today the ICU team continued to follow changes documented in the clinical record.",
        "communication_cautions": ["Do not deliver this draft without clinician approval."],
        "what_not_to_say": ["Do not state prognosis or treatment decisions unless explicitly clinician-approved."],
        "supporting_card_ids": cards[:5],
        "forbidden_use_reminder": [
            "Do not deliver directly to family without clinician approval.",
            "Do not use as prognosis statement.",
            "Do not use as treatment decision.",
        ],
        "requires_clinician_approval_before_delivery": True,
        "human_review_required": True,
    }


def _fallback_payload(task_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    if "patient_memory" in task_name:
        return _memory_fallback(input_payload)
    if "ward_coordinator" in task_name:
        return _ward_fallback(input_payload)
    if "compassion" in task_name or "family" in task_name:
        return _family_fallback(input_payload)
    if "risk" in task_name:
        return _risk_fallback(input_payload)
    return _summary_fallback(input_payload)


def _parse_content(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        if isinstance(message.get("content"), str):
            return message["content"]
    if isinstance(body.get("content"), str):
        return body["content"]
    return json.dumps(body)


def _parse_llm_json_object(raw: str) -> dict[str, Any]:
    """Parse model text into a JSON object (handles ```json fences and prose wrappers)."""
    text = raw.strip()
    if not text:
        raise ValueError("empty LLM response")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON root must be an object")
    return parsed


def generate_structured_output(
    task_name: str,
    prompt_template: str,
    input_payload: dict[str, Any],
    output_schema: type[T],
    model: str | None = None,
    temperature: float = 0.0,
    llm_enabled: bool | None = None,
) -> StructuredOutputResult:
    settings = get_settings()
    enabled = settings.llm_enabled if llm_enabled is None else llm_enabled
    selected_model = model or settings.llm_model
    fallback = _fallback_payload(task_name, input_payload)
    error: str | None = None
    raw_output: Any = None
    parsed: dict[str, Any] | None = None
    schema_valid = False
    safety_valid = False
    fallback_used = True
    llm_used = False

    if enabled and settings.effective_llm_api_key():
        schema_hint = json.dumps(output_schema.model_json_schema(), ensure_ascii=False)
        system_content = (
            f"{prompt_template}\n\n"
            "Respond with ONE raw JSON object only (no markdown fences, no extra text). "
            f"Your JSON MUST validate against this schema:\n{schema_hint}"
        )
        request_payload = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": json.dumps(input_payload, ensure_ascii=False)},
            ],
            "temperature": temperature,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {settings.effective_llm_api_key()}", "Content-Type": "application/json"}
        url = chat_completions_url(settings.effective_llm_base_url())
        last_exc: Exception | None = None
        attempts = max(1, int(settings.llm_max_retries) + 1)
        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                    resp = client.post(url, json=request_payload, headers=headers)
                resp.raise_for_status()
                raw_output = _parse_content(resp.json())
                parsed = _parse_llm_json_object(raw_output)
                output = output_schema.model_validate(parsed)
                schema_valid = True
                # Post-LLM medical safety filter (off by default; see llm/safety.py)
                safety_valid, violations = validate_llm_medical_safety(
                    task_name,
                    output.model_dump(mode="json"),
                    input_payload.get("global_forbidden_use", []),
                )
                if not safety_valid:
                    error = "; ".join(violations)
                    raise ValueError(error)
                llm_used = True
                fallback_used = False
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                error = str(exc)
                retryable = "502" in error or "503" in error or "504" in error or "timeout" in error.lower()
                if attempt + 1 < attempts and retryable:
                    continue
        if last_exc is not None:
            output = output_schema.model_validate(fallback)
    else:
        output = output_schema.model_validate(fallback)

    if fallback_used:
        schema_valid = True
        safety_valid = True
    audit_id = write_llm_audit(
        {
            "task_name": task_name,
            "agent_name": input_payload.get("agent_name"),
            "patient_id": input_payload.get("patient_id"),
            "prompt_template": input_payload.get("prompt_template_name"),
            "input_payload": input_payload,
            "retrieved_card_ids": _card_ids(input_payload),
            "model": selected_model,
            "llm_enabled": bool(enabled),
            "raw_output": raw_output,
            "parsed_output": parsed,
            "schema_valid": schema_valid,
            "safety_valid": safety_valid,
            "fallback_used": fallback_used,
            "error": error,
        }
    )
    return StructuredOutputResult(output=output, llm_used=llm_used, fallback_used=fallback_used, audit_log_id=audit_id, error=error)
