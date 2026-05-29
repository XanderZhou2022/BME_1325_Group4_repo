from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.config import get_settings

from .audit import write_llm_audit
from .concurrency import llm_request_slot
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
    icu_status = input_payload.get("icu_status") if isinstance(input_payload.get("icu_status"), dict) else {}
    queue = [item for item in input_payload.get("priority_queue", []) if isinstance(item, dict)]
    immediate = [str(item.get("bed_id")) for item in queue if str(item.get("priority_level")) == "immediate"]
    urgent = [str(item.get("bed_id")) for item in queue if str(item.get("priority_level")) == "urgent"]
    ref_titles = [str(c.get("title") or c.get("card_id")) for c in input_payload.get("retrieved_knowledge_cards", []) if isinstance(c, dict)]
    rationales = []
    for item in queue:
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
        "ward_overview": (
            f"当前 ICU 共有 {icu_status.get('occupied_beds', len(queue))} 位在院患者，"
            f"其中 critical {icu_status.get('critical_patients', 0)} 位，高风险 {icu_status.get('high_risk_patients', 0)} 位，"
            f"近 1 小时新恶化 {icu_status.get('new_deteriorations', 0)} 位。整体需要继续严密观察。"
        ),
        "priority_reasoning": (
            "当前排布依据规则化优先级评分：风险等级、活动风险数量、近期恶化、干预后反应和未解决关键问题共同决定排序。"
        ),
        "references_used": ref_titles[:5] or cards[:5],
        "next_step_plan": [
            "优先复核 immediate/urgent 床位的最新生命体征、风险输出和未解决问题。",
            "在下一轮病区评估中确认高优先级患者是否出现新的恶化或稳定趋势。",
            "所有排序仅作为临床复核线索，不替代医生决策。",
        ],
        "focus_points": [
            "重点关注 immediate 床位：" + ", ".join(immediate) if immediate else "暂无 immediate 床位，但仍需关注高风险患者。",
            "重点关注 urgent 床位：" + ", ".join(urgent) if urgent else "暂无 urgent 床位。",
            "关注新恶化和未解决关键问题，因为它们会改变病区优先级。",
        ],
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
    summary = input_payload.get("clinical_summary") if isinstance(input_payload.get("clinical_summary"), dict) else {}
    risk = input_payload.get("risk_sentinel_high_level") if isinstance(input_payload.get("risk_sentinel_high_level"), dict) else {}
    status = str(summary.get("one_line_status") or "目前 ICU 团队正在持续观察病情变化")
    watch_items = summary.get("watch_items") if isinstance(summary.get("watch_items"), list) else []
    active_risks = risk.get("active_risks") if isinstance(risk.get("active_risks"), list) else []
    care_focus = "、".join(str(x) for x in watch_items[:3]) if watch_items else "生命体征、检查结果和对治疗支持的反应"
    risk_text = "、".join(str((x or {}).get("risk_type") or x) for x in active_risks[:3]) if active_risks else "需要继续观察的风险信号"
    return {
        "patient_id": str(input_payload.get("patient_id", "")),
        "draft_type": str(input_payload.get("draft_type", "daily_family_update_draft")),
        "clinician_review_version": "以下内容仅供医生审核后用于家属沟通，请勿直接发送。",
        "family_plain_language_draft": (
            f"家属您好，先和您说明一下目前的情况：{status}。"
            f"现在 ICU 团队重点关注的是{care_focus}。"
            f"目前看到的主要风险信号包括{risk_text}，所以仍需要严密监测。"
            "接下来的目标是尽量让各项指标朝稳定方向变化；我们希望情况逐步好转，"
            "但现在还不能做确定承诺，需要根据后续生命体征、化验和治疗反应继续判断。"
            "这段话需要主管医生审核后再向家属说明。"
        ),
        "icu_diary_draft": "今天 ICU 团队继续密切观察病情变化，重点看生命体征、检查结果以及治疗支持后的反应，希望身体指标逐步趋于稳定。",
        "communication_cautions": ["需医生审核后再沟通。", "不要承诺一定好转。", "不要加入输入资料之外的新治疗方案。"],
        "what_not_to_say": ["不要说预后已经确定。", "不要说治疗一定有效。", "不要直接给出未经医生确认的治疗决策。"],
        "supporting_card_ids": cards[:5],
        "forbidden_use_reminder": [
            "未经医生审核不要直接交给家属。",
            "不要作为确定预后说明。",
            "不要作为治疗决策或医嘱。",
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
        agent_name = str(input_payload.get("agent_name") or task_name.split("_")[0])
        patient_id = input_payload.get("patient_id")
        llm_started = time.perf_counter()
        try:
            from app.demo.progress import emit as demo_emit

            demo_emit(
                {
                    "type": "llm_start",
                    "agent_name": agent_name,
                    "task_name": task_name,
                    "model": selected_model,
                    "patient_id": patient_id,
                    "admission_id": input_payload.get("admission_id"),
                }
            )
        except ImportError:
            demo_emit = None  # type: ignore[assignment,misc]
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
                with llm_request_slot(), httpx.Client(timeout=settings.llm_timeout_seconds) as client:
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
        try:
            from app.demo.progress import emit as demo_emit_end

            demo_emit_end(
                {
                    "type": "llm_end",
                    "agent_name": agent_name,
                    "task_name": task_name,
                    "duration_ms": int((time.perf_counter() - llm_started) * 1000),
                    "llm_used": llm_used,
                    "fallback_used": fallback_used,
                    "error": error,
                }
            )
        except (ImportError, NameError):
            pass
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
