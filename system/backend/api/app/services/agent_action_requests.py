from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.schemas import LabEventCreate
from app.services.agent_observability import emit_agent_action_request_event
from app.services.event_pipeline import write_lab
from app.services.ids import new_id
from knowledge.retriever import retrieve_cards

RequestType = Literal["lab", "mdt_consultation"]
RequestStatus = Literal["pending", "completed", "failed"]

LAB_KEYWORD_MAP: dict[str, tuple[str, ...]] = {
    "lactate": ("lactate", "乳酸", "lactic acid", "lactic"),
    "creatinine": ("creatinine", "肌酐", "renal function", "肾功能"),
    "abg": ("abg", "血气", "blood gas", "arterial blood gas"),
    "wbc": ("wbc", "白细胞", "white blood cell"),
    "troponin": ("troponin", "肌钙蛋白", "acs", "ischemic", "ischemia", "st elevation", "心梗", "急性冠脉"),
    "electrolytes": ("electrolyte", "electrolytes", "potassium", "sodium", "钾", "钠", "电解质", "hyperkalemia", "hyponatremia"),
    "glucose": ("glucose", "hyperglycemia", "blood sugar", "血糖", "高血糖", "dka", "hhs"),
    "ketones": ("ketone", "ketones", "酮", "酮体", "dka"),
    "coagulation_panel": ("coagulation", "coagulopathy", "inr", "pt", "aptt", "fibrinogen", "凝血", "纤维蛋白原"),
    "hemoglobin": ("hemoglobin", "haemoglobin", "hgb", "hb", "falling hemoglobin", "血红蛋白", "出血"),
}

MDT_KEYWORDS = (
    "mdt",
    "会诊",
    "multidisciplinary",
    "术前",
    "surgical plan",
    "手术方案",
    "operative",
)

DOMAIN_LAB_HINTS: dict[str, tuple[str, ...]] = {
    "sepsis_shock": ("lactate", "wbc"),
    "ards_respiratory_failure": ("abg",),
    "aki_renal_failure": ("creatinine", "electrolytes"),
    "cardiogenic_shock_acs": ("troponin", "lactate", "electrolytes"),
    "neurocritical_stroke_seizure": ("electrolytes", "glucose"),
    "metabolic_hyperglycemic_crisis": ("glucose", "ketones", "electrolytes", "abg"),
    "electrolyte_disorders": ("electrolytes",),
    "trauma_major_bleeding": ("hemoglobin", "coagulation_panel", "lactate"),
    "medication_safety": ("creatinine", "electrolytes"),
}

DOMAIN_MDT_HINTS = {
    "cardiogenic_shock_acs",
    "neurocritical_stroke_seizure",
    "trauma_major_bleeding",
    "sepsis_shock",
    "ards_respiratory_failure",
}

LAB_REVIEW_LABELS: dict[str, str] = {
    "lactate": "perfusion and shock trajectory",
    "creatinine": "renal function and AKI trajectory",
    "abg": "oxygenation, ventilation, and acid-base status",
    "wbc": "infection or inflammatory trend",
    "troponin": "possible myocardial ischemia or cardiogenic shock context",
    "electrolytes": "potassium/sodium safety and arrhythmia or neurologic risk",
    "glucose": "hyperglycemic crisis or neurologic/metabolic context",
    "ketones": "DKA metabolic context",
    "coagulation_panel": "coagulopathy and bleeding risk",
    "hemoglobin": "bleeding severity and transfusion-response context",
}


def ensure_agent_action_requests_table(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_action_requests (
                request_id TEXT PRIMARY KEY,
                admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
                patient_id TEXT NOT NULL,
                bed_id TEXT NOT NULL,
                request_type TEXT NOT NULL CHECK (request_type IN ('lab', 'mdt_consultation')),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'completed', 'failed')),
                requested_by_agent TEXT NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                source_output_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                fulfilled_at TIMESTAMPTZ,
                fulfillment_detail JSONB
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agent_action_requests_pending
            ON agent_action_requests (admission_id, status)
            WHERE status = 'pending';
            """
        )


def _infer_lab_types_from_texts(texts: list[str]) -> list[str]:
    found: list[str] = []
    blob = " ".join(t for t in texts if t).casefold()
    for lab_type, keywords in LAB_KEYWORD_MAP.items():
        if any(kw.casefold() in blob for kw in keywords):
            found.append(lab_type)
    if not found and re.search(r"(化验|检验|lab|check|复查|检测)", blob):
        found.append("lactate")
    return found


def _cards_from_value(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    cards: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("card_id"):
            cards.append(value)
        for key in ("knowledge_context", "knowledge_background", "retrieved_cards"):
            nested = value.get(key)
            if isinstance(nested, list):
                cards.extend([x for x in nested if isinstance(x, dict) and x.get("card_id")])
        for nested_value in value.values():
            if isinstance(nested_value, (dict, list)):
                cards.extend(_cards_from_value(nested_value))
    elif isinstance(value, list):
        for item in value:
            cards.extend(_cards_from_value(item))
    uniq: dict[str, dict[str, Any]] = {}
    for card in cards:
        uniq[str(card["card_id"])] = card
    return list(uniq.values())


def _card_ids(cards: list[dict[str, Any]], limit: int = 6) -> list[str]:
    return [str(c.get("card_id")) for c in cards if c.get("card_id")][:limit]


def _card_domains(cards: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(str(c.get("domain")) for c in cards if c.get("domain")))


def _knowledge_rationale(cards: list[dict[str, Any]], fallback: str) -> str:
    if not cards:
        return fallback
    topics = [str(c.get("card_type") or c.get("topic") or c.get("domain")) for c in cards[:3]]
    card_ids = ", ".join(_card_ids(cards, limit=3))
    return f"{fallback} Knowledge cards ({card_ids}) provide review-only context for: {', '.join(topics)}."


def _next_steps_from_cards(cards: list[dict[str, Any]], request_type: RequestType, lab_type: str | None = None) -> list[str]:
    domains = set(_card_domains(cards))
    steps: list[str] = []
    if request_type == "lab" and lab_type:
        label = LAB_REVIEW_LABELS.get(lab_type, f"{lab_type}-related trend")
        steps.append(f"Clinician to review updated {lab_type} result in the context of {label}.")
    if "sepsis_shock" in domains:
        steps.append("Review infection, perfusion, lactate, and shock trajectory together.")
    if "ards_respiratory_failure" in domains:
        steps.append("Review oxygenation trend, respiratory support burden, and ventilator-response context.")
    if "aki_renal_failure" in domains:
        steps.append("Review urine output, creatinine trend, renal perfusion, and medication-safety context.")
    if "cardiogenic_shock_acs" in domains:
        steps.append("Review ECG/troponin/hemodynamics together and consider cardiac-specialist review.")
    if "neurocritical_stroke_seizure" in domains:
        steps.append("Review neurologic trajectory, airway risk, seizure/stroke context, and time-sensitive documentation.")
    if "metabolic_hyperglycemic_crisis" in domains:
        steps.append("Review glucose, ketone/anion-gap, osmolality, potassium, and mental-status trajectory.")
    if "electrolyte_disorders" in domains:
        steps.append("Review electrolyte trend with ECG, neurologic symptoms, renal function, and correction safety.")
    if "trauma_major_bleeding" in domains:
        steps.append("Review bleeding source, hemoglobin trend, coagulation context, and transfusion response.")
    if request_type == "mdt_consultation":
        steps.append("MDT output must remain clinician-reviewed and must not be treated as an automatic order set.")
    if not steps:
        steps.append("Clinician to interpret this request with the latest structured ICU data and knowledge-card context.")
    return list(dict.fromkeys(steps))[:6]


def build_knowledge_guided_review_steps(cards: list[dict[str, Any]]) -> list[str]:
    """Review-only next steps grounded in retrieved cards; never returns orders."""
    return _next_steps_from_cards(cards, "mdt_consultation")


def _lab_types_from_cards(cards: list[dict[str, Any]]) -> list[str]:
    inferred: list[str] = []
    texts: list[str] = []
    for card in cards:
        domain = str(card.get("domain") or "")
        inferred.extend(DOMAIN_LAB_HINTS.get(domain, ()))
        texts.extend(
            [
                str(card.get("topic") or ""),
                str(card.get("clinical_context") or ""),
                " ".join(str(x) for x in card.get("trigger_signals") or []),
                " ".join(str(x) for x in card.get("retrieval_keywords") or []),
            ]
        )
    inferred.extend(_infer_lab_types_from_texts(texts))
    return list(dict.fromkeys(inferred))


def _fallback_retrieve_cards(source: str, texts: list[str]) -> list[dict[str, Any]]:
    query = " ".join(str(t) for t in texts if t).strip()
    if not query:
        return []
    agent_name = "risk_sentinel" if source == "risk_sentinel" else "clinical_summary"
    risk_types = [
        token
        for token in re.findall(r"[a-z_]+_risk", query.lower())
        if token
    ]
    retrieval = retrieve_cards(
        agent_name,
        {"patient_id": "action_request"},
        risk_types=list(dict.fromkeys(risk_types)),
        trigger_signals=list(dict.fromkeys(query.split()))[:20],
        query=query,
        top_k=6,
    )
    return [c for c in retrieval.get("retrieved_cards", []) if isinstance(c, dict)]


def _knowledge_payload(
    *,
    request_type: RequestType,
    cards: list[dict[str, Any]],
    base_reason: str,
    lab_type: str | None = None,
    source: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(extra or {})
    if request_type == "lab":
        payload["lab_type"] = lab_type or str(payload.get("lab_type") or "lactate")
        payload["request"] = str(payload.get("request") or f"Request new lab test: {payload['lab_type']}")
    else:
        payload["request"] = str(payload.get("request") or "Request new MDT consultation")
    payload["reason"] = _knowledge_rationale(cards, base_reason)
    payload["knowledge_used"] = bool(cards)
    payload["supporting_card_ids"] = _card_ids(cards)
    payload["supporting_knowledge_domains"] = _card_domains(cards)
    payload["knowledge_rationale"] = payload["reason"]
    payload["clinician_review_next_steps"] = _next_steps_from_cards(cards, request_type, payload.get("lab_type"))
    payload["source"] = source
    payload["human_review_required"] = True
    payload["forbidden_use_reminder"] = [
        "This request is review support only.",
        "Do not treat it as an automatic diagnosis, medication order, procedure order, or treatment plan.",
        "A licensed clinician must decide whether and how to act.",
    ]
    return payload


def _wants_mdt_from_texts(texts: list[str]) -> bool:
    blob = " ".join(t for t in texts if t).casefold()
    return any(kw.casefold() in blob for kw in MDT_KEYWORDS)


def _default_request_text(request_type: RequestType, payload: dict[str, Any]) -> str:
    if request_type == "lab":
        lab_type = str(payload.get("lab_type") or "lactate")
        return f"Request new lab test: {lab_type}"
    return "Request new MDT consultation"


def _default_reason_text(request_type: RequestType, payload: dict[str, Any]) -> str:
    reason = str(payload.get("reason") or "").strip()
    if reason:
        return reason
    if request_type == "lab":
        lab_type = str(payload.get("lab_type") or "lactate")
        return f"Agent identified a need to reassess {lab_type}-related clinical signals."
    return "Agent identified a high-risk or unresolved situation requiring multidisciplinary review."


def _normalize_action_payload(request_type: RequestType, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["request"] = str(normalized.get("request") or _default_request_text(request_type, normalized))
    normalized["reason"] = _default_reason_text(request_type, normalized)
    normalized["human_review_required"] = bool(normalized.get("human_review_required", True))
    normalized.setdefault("knowledge_used", bool(normalized.get("supporting_card_ids")))
    normalized.setdefault("supporting_card_ids", [])
    normalized.setdefault("supporting_knowledge_domains", [])
    normalized.setdefault("clinician_review_next_steps", [])
    normalized.setdefault(
        "forbidden_use_reminder",
        [
            "This request is review support only.",
            "Do not treat it as an automatic diagnosis, medication order, procedure order, or treatment plan.",
            "A licensed clinician must decide whether and how to act.",
        ],
    )
    if request_type == "lab":
        normalized["lab_type"] = str(normalized.get("lab_type") or "lactate")
    return normalized


def _has_pending(
    conn: Connection,
    *,
    admission_id: str,
    request_type: RequestType,
    lab_type: str | None = None,
) -> bool:
    ensure_agent_action_requests_table(conn)
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        if request_type == "lab" and lab_type:
            cur.execute(
                """
                SELECT 1 FROM agent_action_requests
                WHERE admission_id = %s AND request_type = 'lab' AND status = 'pending'
                  AND payload->>'lab_type' = %s
                LIMIT 1
                """,
                (admission_id, lab_type),
            )
        else:
            cur.execute(
                """
                SELECT 1 FROM agent_action_requests
                WHERE admission_id = %s AND request_type = %s AND status = 'pending'
                LIMIT 1
                """,
                (admission_id, request_type),
            )
        return cur.fetchone() is not None


def enqueue_action_request(
    conn: Connection,
    *,
    admission_id: str,
    patient_id: str,
    bed_id: str,
    request_type: RequestType,
    requested_by_agent: str,
    payload: dict[str, Any],
    source_output_id: str | None = None,
) -> str | None:
    """Enqueue if not duplicate pending. Returns request_id or None if skipped."""
    ensure_agent_action_requests_table(conn)
    payload = _normalize_action_payload(request_type, payload)
    lab_type = str(payload.get("lab_type") or "") if request_type == "lab" else None
    if _has_pending(conn, admission_id=admission_id, request_type=request_type, lab_type=lab_type or None):
        return None

    request_id = new_id("areq")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_action_requests (
                request_id, admission_id, patient_id, bed_id, request_type, status,
                requested_by_agent, payload, source_output_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s::jsonb, %s, %s)
            """,
            (
                request_id,
                admission_id,
                patient_id,
                bed_id,
                request_type,
                requested_by_agent,
                Json(payload),
                source_output_id,
                datetime.now(timezone.utc),
            ),
        )

    event_type = "action_request.lab_raised" if request_type == "lab" else "action_request.mdt_consultation_raised"
    emit_agent_action_request_event(
        conn,
        admission_id=admission_id,
        patient_id=patient_id,
        bed_id=bed_id,
        producer_agent=requested_by_agent,
        event_type=event_type,
        payload={
            "request_id": request_id,
            "request_type": request_type,
            **payload,
        },
    )
    return request_id


def derive_requests_from_clinical_summary(summary: Any, *, output_id: str | None = None) -> list[dict[str, Any]]:
    texts = (
        list(getattr(summary, "uncertainties_or_missing_data", []) or [])
        + list(getattr(summary, "recommended_attention_targets", []) or [])
        + list(getattr(summary, "watch_items", []) or [])
        + list(getattr(summary, "review_reminders", []) or [])
        + list(getattr(summary, "clinician_review_next_steps", []) or [])
        + [str(getattr(summary, "one_line_status", "") or "")]
    )
    cards = _cards_from_value(getattr(summary, "knowledge_context", []) or [])
    if not cards:
        cards = _fallback_retrieve_cards("clinical_summary", texts)
    specs: list[dict[str, Any]] = []
    urgency = str(getattr(summary, "urgency_level", "") or "")
    domains = set(_card_domains(cards))
    if urgency == "critical" or _wants_mdt_from_texts(texts) or domains & DOMAIN_MDT_HINTS:
        base_reason = "Clinical summary flagged critical status, MDT need, or high-complexity knowledge domain for clinician review."
        specs.append(
            {
                "request_type": "mdt_consultation",
                "payload": _knowledge_payload(
                    request_type="mdt_consultation",
                    cards=cards,
                    base_reason=base_reason,
                    source="clinical_summary",
                    extra={
                        "urgency_level": urgency,
                        "questions_for_mdt": _next_steps_from_cards(cards, "mdt_consultation"),
                    },
                ),
            }
        )
    risk_blob = " ".join(texts).casefold()
    if "risk" in risk_blob or "risk_assessment" in risk_blob:
        specs.append(
            {
                "request_type": "lab",
                "payload": _knowledge_payload(
                    request_type="lab",
                    cards=cards,
                    base_reason="Clinical summary identified missing/stale risk assessment; lactate can update perfusion-risk context for review.",
                    lab_type="lactate",
                    source="clinical_summary",
                ),
            }
        )
    for lab_type in list(dict.fromkeys(_infer_lab_types_from_texts(texts) + _lab_types_from_cards(cards))):
        specs.append(
            {
                "request_type": "lab",
                "payload": _knowledge_payload(
                    request_type="lab",
                    cards=cards,
                    base_reason=f"Clinical summary and retrieved knowledge cards indicate {LAB_REVIEW_LABELS.get(lab_type, lab_type)} should be reassessed.",
                    lab_type=lab_type,
                    source="clinical_summary",
                ),
            }
        )
    return specs


def derive_requests_from_risk_sentinel(response: Any, *, output_id: str | None = None) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    escalation = str(getattr(response, "escalation_level", "") or "")
    overall = str(getattr(response, "overall_risk_level", "") or "")
    attention = list(getattr(response, "recommended_next_attention", []) or [])
    flags = list(getattr(response, "new_or_worsening_flags", []) or [])
    risks = list(getattr(response, "active_risks", []) or []) or list(getattr(response, "risks", []) or [])
    cards = _cards_from_value(risks)
    texts = attention + flags + [overall, escalation] + [str(getattr(r, "risk_type", "") or "") for r in risks]
    if not cards:
        cards = _fallback_retrieve_cards("risk_sentinel", texts)

    if overall in ("critical", "high") or escalation in ("urgent_review", "immediate_review"):
        specs.append(
            {
                "request_type": "mdt_consultation",
                "payload": _knowledge_payload(
                    request_type="mdt_consultation",
                    cards=cards,
                    base_reason=f"Risk Sentinel escalation ({escalation}) / level ({overall}) requires multidisciplinary clinician review.",
                    source="risk_sentinel",
                    extra={
                        "escalation_level": escalation,
                        "overall_risk_level": overall,
                        "questions_for_mdt": _next_steps_from_cards(cards, "mdt_consultation"),
                    },
                ),
            }
        )
    for lab_type in list(dict.fromkeys(_infer_lab_types_from_texts(texts) + _lab_types_from_cards(cards))):
        specs.append(
            {
                "request_type": "lab",
                "payload": _knowledge_payload(
                    request_type="lab",
                    cards=cards,
                    base_reason=f"Risk Sentinel and retrieved knowledge cards indicate {LAB_REVIEW_LABELS.get(lab_type, lab_type)} should be reassessed.",
                    lab_type=lab_type,
                    source="risk_sentinel",
                    extra={"escalation_level": escalation, "overall_risk_level": overall},
                ),
            }
        )
    if not specs and overall in ("critical", "high"):
        specs.append(
            {
                "request_type": "lab",
                "payload": _knowledge_payload(
                    request_type="lab",
                    cards=cards,
                    base_reason="High risk level; lactate can update perfusion-risk context for clinician review.",
                    lab_type="lactate",
                    source="risk_sentinel",
                    extra={"escalation_level": escalation, "overall_risk_level": overall},
                ),
            }
        )
    return specs


def register_agent_action_requests(
    conn: Connection,
    *,
    admission_id: str,
    patient_id: str,
    bed_id: str,
    requested_by_agent: str,
    specs: list[dict[str, Any]],
    source_output_id: str | None = None,
) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    for spec in specs:
        request_type = spec["request_type"]
        payload = _normalize_action_payload(request_type, spec.get("payload") or {})
        rid = enqueue_action_request(
            conn,
            admission_id=admission_id,
            patient_id=patient_id,
            bed_id=bed_id,
            request_type=request_type,
            requested_by_agent=requested_by_agent,
            payload=payload,
            source_output_id=source_output_id,
        )
        created.append(
            {
                "request_id": rid,
                "request_type": request_type,
                "queued": bool(rid),
                "request": payload["request"],
                "reason": payload["reason"],
                "payload": payload,
            }
        )
    return created


def list_pending_requests(conn: Connection, admission_id: str | None = None) -> list[dict[str, Any]]:
    ensure_agent_action_requests_table(conn)
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        if admission_id:
            cur.execute(
                """
                SELECT request_id, admission_id, patient_id, bed_id, request_type, status,
                       requested_by_agent, payload, source_output_id, created_at
                FROM agent_action_requests
                WHERE admission_id = %s AND status = 'pending'
                ORDER BY created_at ASC
                """,
                (admission_id,),
            )
        else:
            cur.execute(
                """
                SELECT request_id, admission_id, patient_id, bed_id, request_type, status,
                       requested_by_agent, payload, source_output_id, created_at
                FROM agent_action_requests
                WHERE status = 'pending'
                ORDER BY created_at ASC
                """
            )
        return [dict(r) for r in cur.fetchall()]


def _mark_request(
    conn: Connection,
    request_id: str,
    *,
    status: RequestStatus,
    fulfillment_detail: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_action_requests
            SET status = %s, fulfilled_at = %s, fulfillment_detail = %s::jsonb
            WHERE request_id = %s
            """,
            (status, datetime.now(timezone.utc), Json(fulfillment_detail), request_id),
        )


def _fulfill_lab_request(
    conn: Connection,
    request: dict[str, Any],
    *,
    sim_time: datetime,
    defer_ward_coordinator: bool = False,
) -> dict[str, Any]:
    admission_id = str(request["admission_id"])
    patient_id = str(request["patient_id"])
    bed_id = str(request["bed_id"])
    request_id = str(request["request_id"])
    payload = request.get("payload") or {}
    lab_type = str(payload.get("lab_type") or "lactate")
    request_text = str(payload.get("request") or _default_request_text("lab", payload))
    reason = str(payload.get("reason") or _default_reason_text("lab", payload))

    emit_agent_action_request_event(
        conn,
        admission_id=admission_id,
        patient_id=patient_id,
        bed_id=bed_id,
        producer_agent=str(request["requested_by_agent"]),
        event_type="action_request.lab_started",
        payload={"request_id": request_id, "request": request_text, "reason": reason, "lab_type": lab_type, **payload},
    )

    abnormal = random.choice(["normal", "high", "low"])
    if lab_type in ("lactate", "creatinine"):
        abnormal = random.choice(["high", "low", "high"])
    unit_map = {"lactate": "mmol/L", "creatinine": "umol/L", "abg": "unit", "wbc": "10^9/L"}
    lab_body = LabEventCreate(
        timestamp=sim_time,
        source="lab",
        priority="normal",
        lab_type=lab_type,
        value=Decimal(str(round(random.uniform(1.0, 6.0), 2))),
        unit=unit_map.get(lab_type, "unit"),
        abnormal_flag=abnormal,
    )
    write_result = write_lab(conn, admission_id, lab_body)
    from app.orchestrator.event_dispatcher import dispatch_event_chain

    dispatch_result = dispatch_event_chain(
        conn,
        admission_id=admission_id,
        event_type="lab",
        detail_id=write_result["detail_id"],
        defer_ward_coordinator=defer_ward_coordinator,
    )

    detail = {
        "request": request_text,
        "reason": reason,
        "lab_type": lab_type,
        "knowledge_used": bool(payload.get("knowledge_used")),
        "supporting_card_ids": payload.get("supporting_card_ids") or [],
        "supporting_knowledge_domains": payload.get("supporting_knowledge_domains") or [],
        "clinician_review_next_steps": payload.get("clinician_review_next_steps") or [],
        "forbidden_use_reminder": payload.get("forbidden_use_reminder") or [],
        "write_result": write_result,
        "dispatch_result": dispatch_result,
    }
    _mark_request(conn, request_id, status="completed", fulfillment_detail=detail)
    emit_agent_action_request_event(
        conn,
        admission_id=admission_id,
        patient_id=patient_id,
        bed_id=bed_id,
        producer_agent="icu_action_fulfiller",
        event_type="action_request.lab_completed",
        payload={"request_id": request_id, **detail},
    )
    return {
        "type": "agent_request_lab_fulfilled",
        "request_id": request_id,
        "admission_id": admission_id,
        "requested_by_agent": request["requested_by_agent"],
        "request": request_text,
        "reason": reason,
        "lab_type": lab_type,
        "knowledge_used": bool(payload.get("knowledge_used")),
        "supporting_card_ids": payload.get("supporting_card_ids") or [],
        "supporting_knowledge_domains": payload.get("supporting_knowledge_domains") or [],
        "clinician_review_next_steps": payload.get("clinician_review_next_steps") or [],
        "write_result": write_result,
        "dispatch_result": dispatch_result,
    }


def _fulfill_mdt_request(
    conn: Connection,
    request: dict[str, Any],
) -> dict[str, Any]:
    from app.services.mdt_bundle import build_icu_native_bundle
    from app.services.mdt_client import SimiMdtError, post_icu_workflow
    from app.services.mdt_persist import save_mdt_agent_output

    admission_id = str(request["admission_id"])
    patient_id = str(request["patient_id"])
    bed_id = str(request["bed_id"])
    request_id = str(request["request_id"])
    payload = request.get("payload") or {}
    reason = str(payload.get("reason") or "Agent-requested MDT consultation")
    request_text = str(payload.get("request") or _default_request_text("mdt_consultation", payload))

    emit_agent_action_request_event(
        conn,
        admission_id=admission_id,
        patient_id=patient_id,
        bed_id=bed_id,
        producer_agent=str(request["requested_by_agent"]),
        event_type="action_request.mdt_consultation_started",
        payload={"request_id": request_id, "request": request_text, "reason": reason, **payload},
    )

    try:
        questions_for_mdt = payload.get("questions_for_mdt")
        if not isinstance(questions_for_mdt, list):
            questions_for_mdt = payload.get("clinician_review_next_steps")
        bundle = build_icu_native_bundle(
            conn,
            admission_id,
            reason=reason,
            use_api=False,
            questions_for_mdt=[str(q) for q in questions_for_mdt or []],
            action_request_context={
                "request_id": request_id,
                "request": request_text,
                "reason": reason,
                "requested_by_agent": request["requested_by_agent"],
                "knowledge_used": bool(payload.get("knowledge_used")),
                "supporting_card_ids": payload.get("supporting_card_ids") or [],
                "supporting_knowledge_domains": payload.get("supporting_knowledge_domains") or [],
                "clinician_review_next_steps": payload.get("clinician_review_next_steps") or [],
                "forbidden_use_reminder": payload.get("forbidden_use_reminder") or [],
            },
        )
        bridge = post_icu_workflow(bundle)
        output_id = save_mdt_agent_output(
            conn,
            admission_id=admission_id,
            patient_id=patient_id,
            bed_id=bed_id,
            bridge_response=bridge,
        )
        detail = {
            "request": request_text,
            "reason": reason,
            "knowledge_used": bool(payload.get("knowledge_used")),
            "supporting_card_ids": payload.get("supporting_card_ids") or [],
            "supporting_knowledge_domains": payload.get("supporting_knowledge_domains") or [],
            "clinician_review_next_steps": payload.get("clinician_review_next_steps") or [],
            "forbidden_use_reminder": payload.get("forbidden_use_reminder") or [],
            "consultation_id": bridge.get("consultation_id"),
            "mdt_output_type": bridge.get("mdt_output_type"),
            "output_id": output_id,
            "bridge": bridge,
        }
        _mark_request(conn, request_id, status="completed", fulfillment_detail=detail)
        emit_agent_action_request_event(
            conn,
            admission_id=admission_id,
            patient_id=patient_id,
            bed_id=bed_id,
            producer_agent="icu_action_fulfiller",
            event_type="action_request.mdt_consultation_completed",
            payload={"request_id": request_id, **detail},
        )
        return {
            "type": "agent_request_mdt_fulfilled",
            "request_id": request_id,
            "admission_id": admission_id,
            "requested_by_agent": request["requested_by_agent"],
            "request": request_text,
            "reason": reason,
            **detail,
        }
    except SimiMdtError as exc:
        detail = {"request": request_text, "reason": reason, "error": exc.message, "code": exc.code}
        _mark_request(conn, request_id, status="failed", fulfillment_detail=detail)
        emit_agent_action_request_event(
            conn,
            admission_id=admission_id,
            patient_id=patient_id,
            bed_id=bed_id,
            producer_agent="icu_action_fulfiller",
            event_type="action_request.mdt_consultation_failed",
            payload={"request_id": request_id, **detail},
        )
        return {
            "type": "agent_request_mdt_failed",
            "request_id": request_id,
            "admission_id": admission_id,
            "requested_by_agent": request["requested_by_agent"],
            "request": request_text,
            "reason": reason,
            "error": exc.message,
        }


def fulfill_pending_requests_for_admission(
    conn: Connection,
    admission: dict[str, Any],
    *,
    sim_time: datetime,
    defer_ward_coordinator: bool = False,
) -> list[dict[str, Any]]:
    admission_id = str(admission["admission_id"])
    pending = list_pending_requests(conn, admission_id)
    if not pending:
        return []

    results: list[dict[str, Any]] = []
    for req in pending:
        if req["request_type"] == "lab":
            results.append(_fulfill_lab_request(conn, req, sim_time=sim_time, defer_ward_coordinator=defer_ward_coordinator))
        elif req["request_type"] == "mdt_consultation":
            results.append(_fulfill_mdt_request(conn, req))
    return results
