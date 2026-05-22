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

RequestType = Literal["lab", "mdt_consultation"]
RequestStatus = Literal["pending", "completed", "failed"]

LAB_KEYWORD_MAP: dict[str, tuple[str, ...]] = {
    "lactate": ("lactate", "乳酸", "lactic acid", "lactic"),
    "creatinine": ("creatinine", "肌酐", "renal function", "肾功能"),
    "abg": ("abg", "血气", "blood gas", "arterial blood gas"),
    "wbc": ("wbc", "白细胞", "white blood cell"),
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


def _wants_mdt_from_texts(texts: list[str]) -> bool:
    blob = " ".join(t for t in texts if t).casefold()
    return any(kw.casefold() in blob for kw in MDT_KEYWORDS)


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
        + [str(getattr(summary, "one_line_status", "") or "")]
    )
    specs: list[dict[str, Any]] = []
    urgency = str(getattr(summary, "urgency_level", "") or "")
    if urgency == "critical" or _wants_mdt_from_texts(texts):
        specs.append(
            {
                "request_type": "mdt_consultation",
                "payload": {
                    "reason": "Clinical summary flagged critical status or MDT need",
                    "source": "clinical_summary",
                    "urgency_level": urgency,
                },
            }
        )
    if "risk" in " ".join(texts).casefold() or "risk_assessment" in " ".join(texts).casefold():
        specs.append(
            {
                "request_type": "lab",
                "payload": {
                    "lab_type": "lactate",
                    "reason": "Missing or stale risk assessment — order lactate",
                    "source": "clinical_summary",
                },
            }
        )
    for lab_type in _infer_lab_types_from_texts(texts):
        specs.append(
            {
                "request_type": "lab",
                "payload": {
                    "lab_type": lab_type,
                    "reason": f"Clinical summary requested lab: {lab_type}",
                    "source": "clinical_summary",
                },
            }
        )
    return specs


def derive_requests_from_risk_sentinel(response: Any, *, output_id: str | None = None) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    escalation = str(getattr(response, "escalation_level", "") or "")
    overall = str(getattr(response, "overall_risk_level", "") or "")
    attention = list(getattr(response, "recommended_next_attention", []) or [])
    flags = list(getattr(response, "new_or_worsening_flags", []) or [])
    texts = attention + flags + [overall, escalation]

    if overall in ("critical", "high") or escalation in ("urgent_review", "immediate_review"):
        specs.append(
            {
                "request_type": "mdt_consultation",
                "payload": {
                    "reason": f"Risk sentinel escalation ({escalation}) / level ({overall})",
                    "source": "risk_sentinel",
                    "escalation_level": escalation,
                    "overall_risk_level": overall,
                },
            }
        )
    for lab_type in _infer_lab_types_from_texts(texts):
        specs.append(
            {
                "request_type": "lab",
                "payload": {
                    "lab_type": lab_type,
                    "reason": f"Risk sentinel follow-up lab: {lab_type}",
                    "source": "risk_sentinel",
                },
            }
        )
    if not specs and overall in ("critical", "high"):
        specs.append(
            {
                "request_type": "lab",
                "payload": {
                    "lab_type": "lactate",
                    "reason": "High risk level — default perfusion lab",
                    "source": "risk_sentinel",
                },
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
        rid = enqueue_action_request(
            conn,
            admission_id=admission_id,
            patient_id=patient_id,
            bed_id=bed_id,
            request_type=spec["request_type"],
            requested_by_agent=requested_by_agent,
            payload=spec.get("payload") or {},
            source_output_id=source_output_id,
        )
        created.append(
            {
                "request_id": rid,
                "request_type": spec["request_type"],
                "queued": bool(rid),
                "payload": spec.get("payload") or {},
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

    emit_agent_action_request_event(
        conn,
        admission_id=admission_id,
        patient_id=patient_id,
        bed_id=bed_id,
        producer_agent=str(request["requested_by_agent"]),
        event_type="action_request.lab_started",
        payload={"request_id": request_id, "lab_type": lab_type},
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
        "lab_type": lab_type,
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
        "lab_type": lab_type,
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

    emit_agent_action_request_event(
        conn,
        admission_id=admission_id,
        patient_id=patient_id,
        bed_id=bed_id,
        producer_agent=str(request["requested_by_agent"]),
        event_type="action_request.mdt_consultation_started",
        payload={"request_id": request_id, "reason": reason},
    )

    try:
        bundle = build_icu_native_bundle(conn, admission_id, reason=reason, use_api=False)
        bridge = post_icu_workflow(bundle)
        output_id = save_mdt_agent_output(
            conn,
            admission_id=admission_id,
            patient_id=patient_id,
            bed_id=bed_id,
            bridge_response=bridge,
        )
        detail = {
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
            **detail,
        }
    except SimiMdtError as exc:
        detail = {"error": exc.message, "code": exc.code}
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
