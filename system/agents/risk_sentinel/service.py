from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.agent_action_requests import (
    derive_requests_from_risk_sentinel,
    register_agent_action_requests,
)
from app.services.ids import new_id
from types import SimpleNamespace
from knowledge.retriever import retrieve_cards
from llm.client import generate_structured_output
from llm.prompt_loader import load_prompt_template
from llm.schemas import RiskSentinelLLMOutput

from .schemas import RiskImage, RiskSentinelEvaluateRequest, RiskSentinelEvaluateResponse, RiskSeverity


RISK_TO_ALERT_TYPE: dict[str, str] = {
    "persistent_shock_risk": "shock_risk",
    "respiratory_failure_risk": "resp_failure_risk",
    "aki_risk": "aki_risk",
}

RISK_ORDER = {"low": 0, "moderate": 1, "high": 2, "critical": 3}
LEVEL_TO_ESCALATION = {"low": "info", "moderate": "watch", "high": "urgent_review", "critical": "immediate_review"}
LEVEL_TO_CONFIDENCE = {"low": Decimal("0.62"), "moderate": Decimal("0.75"), "high": Decimal("0.86"), "critical": Decimal("0.94")}
NOTIFY_AGENTS = ["ward_coordinator", "clinical_summary", "patient_memory"]
DB_LEVEL_MAP = {"low": "low", "moderate": "warning", "high": "warning", "critical": "critical"}
SAFE_FORBIDDEN_REMINDER = [
    "Do not use this output as a diagnosis.",
    "Do not use this output as a treatment recommendation.",
    "Clinician review is required.",
]


def _json_safe_risks(risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for risk in risks:
        item = dict(risk)
        conf = item.get("confidence")
        if isinstance(conf, Decimal):
            item["confidence"] = float(conf)
        out.append(item)
    return out


def _level_from_score(score: int) -> str:
    if score >= 7:
        return "critical"
    if score >= 4:
        return "high"
    if score >= 2:
        return "moderate"
    return "low"


def _trajectory_from_signals(signals: list[str]) -> str:
    if any("worsening" in s or "deteriorating" in s or "rising" in s for s in signals):
        return "worsening"
    if any("improving" in s for s in signals):
        return "improving"
    if signals:
        return "stable"
    return "unclear"


def _calculate_risk_from_payloads(
    *,
    bedside_payload: dict[str, Any],
    intervention_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    abnormal_flags = list(bedside_payload.get("abnormal_flags") or [])
    trend_labels = list(bedside_payload.get("trend_labels") or [])
    urgency = str(bedside_payload.get("urgency_level") or "info").lower()
    response_label = str(intervention_payload.get("response_label") or intervention_payload.get("response_assessment") or "")
    intervention_type = str(intervention_payload.get("intervention_type") or "")
    concern_flags = list(intervention_payload.get("concern_flags") or [])
    memory_ctx = dict(intervention_payload.get("memory_context_for_risk") or {})
    unresolved = list(memory_ctx.get("unresolved_issues") or [])

    abnormal_set = {str((f or {}).get("type") if isinstance(f, dict) else f) for f in abnormal_flags}
    trend_set = {str((t or {}).get("metric") + "_" + str((t or {}).get("trend")) if isinstance(t, dict) else t) for t in trend_labels}
    signals: list[str] = []
    new_or_worsening: list[str] = []

    risks: list[dict[str, Any]] = []
    # 1) persistent_shock_risk
    shock_score = 0
    if urgency == "warning":
        shock_score += 1
    if urgency == "critical":
        shock_score += 2
    if any("mean_arterial_pressure" in s and "decreasing" in s for s in trend_set):
        shock_score += 1
        signals.append("map_worsening")
    if any("mean_arterial_pressure" in s or "hypotension" in s for s in abnormal_set):
        shock_score += 1
    if response_label == "partially_responsive":
        shock_score += 1
    if response_label == "non_responsive":
        shock_score += 2
    if response_label == "deteriorating_despite_intervention":
        shock_score += 3
        signals.append("post_intervention_deteriorating")
    if "worsening" in str(memory_ctx.get("recent_trajectory") or ""):
        shock_score += 2
        signals.append("memory_worsening")
    if any("persistent_hypotension" in str(x) for x in unresolved):
        shock_score += 1
    if any("lactate" in str(x) for x in unresolved):
        shock_score += 2
        signals.append("rising_lactate")
    shock_level = _level_from_score(shock_score)
    if shock_score > 0:
        trajectory = _trajectory_from_signals(signals)
        if trajectory == "worsening" and shock_level in ("high", "critical"):
            new_or_worsening.append("shock_risk_worsening")
        risks.append(
            {
                "risk_type": "persistent_shock_risk",
                "risk_level": shock_level,
                "severity": shock_level,
                "confidence": LEVEL_TO_CONFIDENCE[shock_level],
                "evidence": [
                    {"source": "bedside", "abnormal_flags": list(abnormal_set), "trend_labels": list(trend_set)},
                    {"source": "intervention", "response_label": response_label, "intervention_type": intervention_type, "concern_flags": concern_flags},
                    {"source": "patient_memory", "unresolved_issues": unresolved, "recent_trajectory": memory_ctx.get("recent_trajectory")},
                ],
                "time_window": "last_6h",
                "trajectory": trajectory,
                "escalation_level": LEVEL_TO_ESCALATION[shock_level],
                "recommended_action": "Review hemodynamic status and unresolved shock-related signals.",
            }
        )

    # 2) respiratory_failure_risk
    resp_score = 0
    resp_signals: list[str] = []
    if any("spo2" in s and "decreasing" in s for s in trend_set):
        resp_score += 1
        resp_signals.append("spo2_worsening")
    if any("respiratory_rate" in s and "increasing" in s for s in trend_set):
        resp_score += 1
    if any("spo2" in s or "hypoxemia" in s for s in abnormal_set):
        resp_score += 2
    if intervention_type in ("ventilator_adjustment", "ventilator_change") and response_label in ("non_responsive", "deteriorating_despite_intervention"):
        resp_score += 2 if response_label == "non_responsive" else 3
        resp_signals.append("ventilator_non_response")
    resp_level = _level_from_score(resp_score)
    if resp_score > 0:
        resp_traj = _trajectory_from_signals(resp_signals)
        if resp_traj == "worsening" and resp_level in ("high", "critical"):
            new_or_worsening.append("respiratory_risk_worsening")
        risks.append(
            {
                "risk_type": "respiratory_failure_risk",
                "risk_level": resp_level,
                "severity": resp_level,
                "confidence": LEVEL_TO_CONFIDENCE[resp_level],
                "evidence": [
                    {"source": "bedside", "abnormal_flags": list(abnormal_set), "trend_labels": list(trend_set)},
                    {"source": "intervention", "response_label": response_label, "intervention_type": intervention_type},
                ],
                "time_window": "last_6h",
                "trajectory": resp_traj,
                "escalation_level": LEVEL_TO_ESCALATION[resp_level],
                "recommended_action": "Review oxygenation trend and respiratory support burden.",
            }
        )

    # 3) aki_risk
    aki_score = 0
    aki_signals: list[str] = []
    if any("oliguria" in s for s in abnormal_set):
        aki_score += 2
    if any("creatinine" in str(x) for x in unresolved):
        aki_score += 2
        aki_signals.append("creatinine_rising")
    if any("hypotension" in s for s in abnormal_set):
        aki_score += 1
    if response_label in ("non_responsive", "deteriorating_despite_intervention"):
        aki_score += 1
    aki_level = _level_from_score(aki_score)
    if aki_score > 0:
        aki_traj = _trajectory_from_signals(aki_signals)
        if aki_traj == "worsening" and aki_level in ("high", "critical"):
            new_or_worsening.append("aki_risk_worsening")
        risks.append(
            {
                "risk_type": "aki_risk",
                "risk_level": aki_level,
                "severity": aki_level,
                "confidence": LEVEL_TO_CONFIDENCE[aki_level],
                "evidence": [
                    {"source": "bedside", "abnormal_flags": list(abnormal_set)},
                    {"source": "patient_memory", "unresolved_issues": unresolved},
                ],
                "time_window": "last_24h",
                "trajectory": aki_traj,
                "escalation_level": LEVEL_TO_ESCALATION[aki_level],
                "recommended_action": "Review renal perfusion signals and urine-output trajectory.",
            }
        )

    uniq: dict[str, dict[str, Any]] = {}
    for risk in risks:
        risk_type = str(risk["risk_type"])
        if risk_type not in uniq or RISK_ORDER[str(risk["risk_level"])] > RISK_ORDER[str(uniq[risk_type]["risk_level"])]:
            uniq[risk_type] = risk
    return list(uniq.values()), list(dict.fromkeys(new_or_worsening))


def _extract_trigger_signals(risk: dict[str, Any]) -> list[str]:
    signals = [str(risk.get("trajectory") or "")]
    for evidence in risk.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        for key in ("abnormal_flags", "trend_labels", "concern_flags", "unresolved_issues"):
            for item in evidence.get(key) or []:
                signals.append(str(item))
        if evidence.get("response_label"):
            signals.append(str(evidence["response_label"]))
    return [s for s in dict.fromkeys(signals) if s and s != "None"]


def _compact_context(payload: dict[str, Any], max_items: int = 6) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, list):
            out[key] = value[:max_items]
        elif isinstance(value, dict):
            out[key] = {k: value[k] for k in list(value.keys())[:max_items]}
    return out


def enrich_risks_with_knowledge_and_llm(
    *,
    patient_id: str,
    bed_id: str,
    risks: list[dict[str, Any]],
    bedside_payload: dict[str, Any],
    intervention_payload: dict[str, Any],
    memory_payload: dict[str, Any],
    llm_enabled: bool | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not risks:
        return risks, {
            "retrieved_cards": [],
            "llm_used": False,
            "fallback_used": False,
            "audit_log_id": None,
            "overall_review_reminder": "No active rule-based risks were detected.",
            "human_review_required": True,
        }

    risk_types = [str(r["risk_type"]) for r in risks]
    trigger_signals = list(dict.fromkeys(signal for risk in risks for signal in _extract_trigger_signals(risk)))
    retrieval = retrieve_cards(
        "risk_sentinel",
        {"patient_id": patient_id, "bed_id": bed_id},
        risk_types=risk_types,
        trigger_signals=trigger_signals,
        query=" ".join(risk_types + trigger_signals),
    )
    cards = retrieval["retrieved_cards"]
    prompt = load_prompt_template("risk_sentinel_knowledge_prompt.md")
    input_payload = {
        "agent_name": "risk_sentinel",
        "prompt_template_name": "risk_sentinel_knowledge_prompt.md",
        "patient_id": patient_id,
        "time_window": "last_6h",
        "rule_based_risks": [
            {
                "risk_type": str(r.get("risk_type")),
                "risk_level": str(r.get("risk_level")),
                "confidence": float(r.get("confidence", 0)),
                "rule_evidence": r.get("evidence") or [],
                "trigger_signals": _extract_trigger_signals(r),
            }
            for r in risks
        ],
        "patient_context": {
            "recent_vital_summary": _compact_context(bedside_payload),
            "recent_intervention_summary": _compact_context(intervention_payload),
            "memory_summary": _compact_context(memory_payload),
        },
        "retrieved_knowledge_cards": cards,
        "global_constraints": [
            "Do not make a diagnosis.",
            "Do not recommend treatment.",
            "Use knowledge cards only as background.",
            "All outputs require clinician review.",
        ],
        "global_forbidden_use": ["diagnosis", "treatment_recommendation", "automatic_medical_decision", "icu_admission_or_discharge_decision"],
    }
    llm_result = generate_structured_output(
        "risk_sentinel_explanation",
        prompt,
        input_payload,
        RiskSentinelLLMOutput,
        llm_enabled=llm_enabled,
    )
    llm_output = llm_result.output.model_dump(mode="json")
    explanations = {item["risk_type"]: item for item in llm_output.get("risk_explanations", [])}

    enriched: list[dict[str, Any]] = []
    for risk in risks:
        item = dict(risk)
        explanation = explanations.get(str(risk["risk_type"]), {})
        item["trigger_signals"] = _extract_trigger_signals(risk)
        item["knowledge_background"] = cards
        item["llm_explanation"] = explanation.get("explanation") or "A rule-based risk pattern was detected. Clinician review is required."
        item["escalation_rationale"] = explanation.get("escalation_rationale") or "This rule-triggered pattern should remain visible for clinical review."
        item["forbidden_use_reminder"] = explanation.get("forbidden_use_reminder") or SAFE_FORBIDDEN_REMINDER
        item["human_review_required"] = True
        enriched.append(item)

    return enriched, {
        "retrieved_cards": cards,
        "llm_used": llm_result.llm_used,
        "fallback_used": llm_result.fallback_used,
        "audit_log_id": llm_result.audit_log_id,
        "overall_review_reminder": llm_output.get("overall_review_reminder", "Risk Sentinel outputs are decision-support signals only and require clinician review."),
        "human_review_required": True,
    }


def evaluate_risk_sentinel(conn: Connection, req: RiskSentinelEvaluateRequest) -> RiskSentinelEvaluateResponse:
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT patient_id, bed_id
                FROM admissions
                WHERE admission_id = %s
                """,
                (req.admission_id,),
            )
            admission = cur.fetchone()
            if not admission:
                raise HTTPException(status_code=404, detail="Admission not found")
            patient_id = cast(str, admission["patient_id"])
            bed_id = cast(str, admission["bed_id"])

            cur.execute(
                """
                INSERT INTO agent_registry (agent_name, input_event_types, output_event_type, schema_version, enabled)
                VALUES ('risk_sentinel', '["bedside_analysis_ready","intervention_evaluation_ready","patient_memory_ready"]'::jsonb, 'risk_assessment_ready', 'v1', TRUE)
                ON CONFLICT (agent_name) DO UPDATE SET enabled = TRUE, updated_at = NOW()
                """
            )

            last_event_at = None
            if not req.force_recompute:
                cur.execute(
                    """
                    SELECT last_event_at
                    FROM agent_consumption_cursor
                    WHERE consumer_agent = 'risk_sentinel' AND admission_id = %s
                    """,
                    (req.admission_id,),
                )
                cursor_row = cur.fetchone()
                if cursor_row:
                    last_event_at = cursor_row["last_event_at"]

            cur.execute(
                """
                SELECT event_id, producer_agent, produced_at, payload
                FROM agent_events
                WHERE admission_id = %s
                  AND producer_agent = ANY(%s)
                  AND (%s::timestamptz IS NULL OR produced_at > %s::timestamptz)
                ORDER BY produced_at ASC, event_id ASC
                LIMIT %s
                """,
                (req.admission_id, ["bedside_monitor", "intervention_tracker", "patient_memory"], last_event_at, last_event_at, req.max_events),
            )
            events = cur.fetchall()

            consumed_event_ids = [cast(str, e["event_id"]) for e in events]

            cur.execute(
                """
                SELECT payload
                FROM agent_outputs
                WHERE admission_id = %s AND agent_name = 'bedside_monitor'
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (req.admission_id,),
            )
            bedside_row = cur.fetchone()
            bedside_payload = cast(dict[str, Any], (bedside_row["payload"] if bedside_row else {}))

            cur.execute(
                """
                SELECT payload
                FROM agent_outputs
                WHERE admission_id = %s AND agent_name = 'intervention_tracker'
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (req.admission_id,),
            )
            intv_row = cur.fetchone()
            intervention_payload = cast(dict[str, Any], (intv_row["payload"] if intv_row else {}))

            cur.execute(
                """
                SELECT payload
                FROM agent_outputs
                WHERE admission_id = %s AND agent_name = 'patient_memory'
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (req.admission_id,),
            )
            mem_row = cur.fetchone()
            memory_payload = cast(dict[str, Any], (mem_row["payload"] if mem_row else {}))
            intervention_payload = {**intervention_payload, "memory_context_for_risk": memory_payload.get("memory_context_for_risk") or {}}

            risks, new_or_worsening_flags = _calculate_risk_from_payloads(bedside_payload=bedside_payload, intervention_payload=intervention_payload)
            risks, knowledge_meta = enrich_risks_with_knowledge_and_llm(
                patient_id=patient_id,
                bed_id=bed_id,
                risks=risks,
                bedside_payload=bedside_payload,
                intervention_payload=intervention_payload,
                memory_payload=memory_payload,
            )
            overall_risk_level = "low"
            if risks:
                overall_risk_level = max([str(r["risk_level"]) for r in risks], key=lambda x: RISK_ORDER.get(x, 0))

            for risk in risks:
                risk_id = new_id("risk")
                cur.execute(
                    """
                    INSERT INTO risk_assessments (
                        id, admission_id, timestamp, risk_type, confidence, severity, evidence, time_window, recommended_action
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        risk_id,
                        req.admission_id,
                        datetime.now(timezone.utc),
                        risk["risk_type"],
                        risk["confidence"],
                        DB_LEVEL_MAP[str(risk["risk_level"])],
                        Json(risk["evidence"]),
                        risk["time_window"],
                        risk["recommended_action"],
                    ),
                )

                alert_id = new_id("alert")
                cur.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, admission_id, patient_id, bed_id, alert_type, severity, status,
                        source_agent, evidence, first_seen_at, last_seen_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'open', 'risk_sentinel', %s::jsonb, %s, %s)
                    """,
                    (
                        alert_id,
                        req.admission_id,
                        patient_id,
                        bed_id,
                        RISK_TO_ALERT_TYPE.get(str(risk["risk_type"]), f"{risk['risk_type']}_risk"),
                        "critical" if risk["risk_level"] == "critical" else ("warning" if risk["risk_level"] in ("moderate", "high") else "info"),
                        Json(risk["evidence"]),
                        datetime.now(timezone.utc),
                        datetime.now(timezone.utc),
                    ),
                )

            active_risks = [{"risk_type": r["risk_type"], "severity": DB_LEVEL_MAP[str(r["risk_level"])]} for r in risks]
            if active_risks:
                max_sev = max(active_risks, key=lambda x: {"low": 0, "warning": 1, "critical": 2}[str(x["severity"])])["severity"]
                care_phase = "critical" if max_sev == "critical" else "unstable"
                cur.execute(
                    """
                    UPDATE patient_state_current
                    SET active_risks = %s::jsonb, care_phase = %s, updated_at = NOW()
                    WHERE admission_id = %s
                    """,
                    (Json(active_risks), care_phase, req.admission_id),
                )

            payload = {
                "schema_version": "risk_sentinel.v1.1",
                "agent": "risk_sentinel",
                "admission_id": req.admission_id,
                "patient_id": patient_id,
                "bed_id": bed_id,
                "overall_risk_level": overall_risk_level,
                "active_risks": _json_safe_risks(risks),
                "new_or_worsening_flags": new_or_worsening_flags,
                "recommended_next_attention": [str(r["recommended_action"]) for r in risks][:5],
                "notify_agents": NOTIFY_AGENTS,
                "risks": _json_safe_risks(risks),
                "consumed_event_ids": consumed_event_ids,
                "knowledge_retrieval": {
                    "retrieved_card_ids": [c["card_id"] for c in knowledge_meta["retrieved_cards"]],
                    "retrieved_cards": knowledge_meta["retrieved_cards"],
                },
                "overall_review_reminder": knowledge_meta["overall_review_reminder"],
                "llm_used": knowledge_meta["llm_used"],
                "fallback_used": knowledge_meta["fallback_used"],
                "audit_log_id": knowledge_meta["audit_log_id"],
                "human_review_required": True,
            }
            if risks:
                _highest = max(risks, key=lambda r: RISK_ORDER[str(r["risk_level"])])
                _escalation = LEVEL_TO_ESCALATION[str(_highest["risk_level"])]
            else:
                _escalation = "info"
            _risk_stub = SimpleNamespace(
                escalation_level=_escalation,
                overall_risk_level=overall_risk_level,
                recommended_next_attention=payload["recommended_next_attention"],
                new_or_worsening_flags=payload["new_or_worsening_flags"],
            )
            _action_specs = derive_requests_from_risk_sentinel(_risk_stub)
            output_id = new_id("out")
            _action_rows = register_agent_action_requests(
                conn,
                admission_id=req.admission_id,
                patient_id=patient_id,
                bed_id=bed_id,
                requested_by_agent="risk_sentinel",
                specs=_action_specs,
                source_output_id=output_id,
            )
            payload["action_requests"] = _action_rows
            event_id = new_id("aevt")
            cur.execute(
                """
                INSERT INTO agent_outputs (
                    output_id, admission_id, patient_id, bed_id, agent_name,
                    schema_version, output_type, generated_at, payload
                ) VALUES (%s, %s, %s, %s, 'risk_sentinel', 'v1', 'risk_assessment_ready', %s, %s::jsonb)
                """,
                (output_id, req.admission_id, patient_id, bed_id, datetime.now(timezone.utc), Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'risk_sentinel', 'risk_assessment_ready', 'v1', %s, %s, %s::jsonb)
                """,
                (event_id, req.admission_id, patient_id, bed_id, datetime.now(timezone.utc), output_id, Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'risk_sentinel', 'risk_sentinel.completed', 'v1', %s, %s, %s::jsonb)
                """,
                (
                    new_id("aevt"),
                    req.admission_id,
                    patient_id,
                    bed_id,
                    datetime.now(timezone.utc),
                    output_id,
                    Json({"overall_risk_level": overall_risk_level, "new_or_worsening_flags": new_or_worsening_flags}),
                ),
            )
            cur.execute(
                """
                INSERT INTO audit_logs (id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output)
                VALUES (%s, %s, 'agent', 'risk_sentinel', 'run_agent', 'admission', %s, %s::jsonb, %s::jsonb)
                """,
                (
                    new_id("log"),
                    datetime.now(timezone.utc),
                    req.admission_id,
                    Json({"admission_id": req.admission_id, "max_events": req.max_events, "force_recompute": req.force_recompute}),
                    Json({
                        "overall_risk_level": overall_risk_level,
                        "risk_count": len(risks),
                        "new_or_worsening_flags": new_or_worsening_flags,
                        "retrieved_card_ids": [c["card_id"] for c in knowledge_meta["retrieved_cards"]],
                        "llm_audit_log_id": knowledge_meta["audit_log_id"],
                    }),
                ),
            )

            if events:
                last = events[-1]
                cur.execute(
                    """
                    INSERT INTO agent_consumption_cursor (
                        consumer_agent, admission_id, last_event_id, last_event_at, updated_at
                    ) VALUES ('risk_sentinel', %s, %s, %s, NOW())
                    ON CONFLICT (consumer_agent, admission_id) DO UPDATE SET
                        last_event_id = EXCLUDED.last_event_id,
                        last_event_at = EXCLUDED.last_event_at,
                        updated_at = NOW()
                    """,
                    (req.admission_id, last["event_id"], last["produced_at"]),
                )

    if risks:
        highest = max(risks, key=lambda r: RISK_ORDER[str(r["risk_level"])])
        escalation = cast(str, LEVEL_TO_ESCALATION[str(highest["risk_level"])])
        overall = cast(RiskSeverity, str(highest["risk_level"]))
    else:
        escalation = "info"
        overall = cast(RiskSeverity, "low")
    knowledge_meta = locals().get(
        "knowledge_meta",
        {
            "overall_review_reminder": "Risk Sentinel outputs are decision-support signals only and require clinician review.",
            "llm_used": False,
            "fallback_used": True,
            "audit_log_id": None,
        },
    )
    return RiskSentinelEvaluateResponse(
        patient_id=patient_id,
        bed_id=bed_id,
        admission_id=req.admission_id,
        overall_risk_level=overall,
        active_risks=[
            RiskImage(
                risk_type=str(r["risk_type"]),
                confidence=cast(Decimal, r["confidence"]),
                severity=cast(RiskSeverity, str(r["risk_level"])),
                risk_level=cast(RiskSeverity, str(r["risk_level"])),
                evidence=cast(list[dict[str, Any]], r["evidence"]),
                time_window=str(r["time_window"]),
                trajectory=cast(Any, str(r["trajectory"])),
                escalation_level=cast(Any, str(r["escalation_level"])),
                recommended_action=str(r["recommended_action"]),
                trigger_signals=cast(list[str], r.get("trigger_signals") or []),
                knowledge_background=cast(list[dict[str, Any]], r.get("knowledge_background") or []),
                llm_explanation=str(r.get("llm_explanation") or ""),
                escalation_rationale=str(r.get("escalation_rationale") or ""),
                forbidden_use_reminder=cast(list[str], r.get("forbidden_use_reminder") or SAFE_FORBIDDEN_REMINDER),
                human_review_required=True,
            )
            for r in risks
        ],
        new_or_worsening_flags=new_or_worsening_flags if risks else [],
        recommended_next_attention=[str(r["recommended_action"]) for r in risks][:5],
        notify_agents=NOTIFY_AGENTS if risks else [],
        consumed_event_count=len(consumed_event_ids),
        consumed_event_ids=consumed_event_ids,
        risks=[
            RiskImage(
                risk_type=str(r["risk_type"]),
                confidence=cast(Decimal, r["confidence"]),
                severity=cast(RiskSeverity, str(r["risk_level"])),
                risk_level=cast(RiskSeverity, str(r["risk_level"])),
                evidence=cast(list[dict[str, Any]], r["evidence"]),
                time_window=str(r["time_window"]),
                trajectory=cast(Any, str(r["trajectory"])),
                escalation_level=cast(Any, str(r["escalation_level"])),
                recommended_action=str(r["recommended_action"]),
                trigger_signals=cast(list[str], r.get("trigger_signals") or []),
                knowledge_background=cast(list[dict[str, Any]], r.get("knowledge_background") or []),
                llm_explanation=str(r.get("llm_explanation") or ""),
                escalation_rationale=str(r.get("escalation_rationale") or ""),
                forbidden_use_reminder=cast(list[str], r.get("forbidden_use_reminder") or SAFE_FORBIDDEN_REMINDER),
                human_review_required=True,
            )
            for r in risks
        ],
        escalation_level=cast(Any, escalation),
        generated_at=datetime.now(timezone.utc),
        overall_review_reminder=str(knowledge_meta["overall_review_reminder"]),
        llm_used=bool(knowledge_meta["llm_used"]),
        fallback_used=bool(knowledge_meta["fallback_used"]),
        audit_log_id=cast(Any, knowledge_meta["audit_log_id"]),
        human_review_required=True,
    )
