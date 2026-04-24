from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from agents.bedside_monitor.schemas import BedsideAnalyzeRequest
from agents.bedside_monitor.service import analyze_bedside
from agents.clinical_summary.service import evaluate_clinical_summary
from agents.intervention_tracker.schemas import InterventionEvaluateRequest
from agents.intervention_tracker.service import evaluate_intervention_tracker, register_pending_intervention
from agents.patient_memory.schemas import MemoryEvaluateRequest
from agents.patient_memory.service import evaluate_memory
from agents.risk_sentinel.schemas import RiskSentinelEvaluateRequest
from agents.risk_sentinel.service import evaluate_risk_sentinel
from agents.ward_coordinator.schemas import WardCoordinatorEvaluateRequest
from agents.ward_coordinator.service import evaluate_ward
from app.services.agent_observability import emit_agent_lifecycle_event, write_run_audit


def _admission_meta(conn: Connection, admission_id: str) -> dict[str, str] | None:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT patient_id, bed_id FROM admissions WHERE admission_id = %s", (admission_id,))
        row = cur.fetchone()
    if not row:
        return None
    return {"patient_id": row["patient_id"], "bed_id": row["bed_id"]}


def _risk_requires_escalation(risk_out: Any) -> bool:
    if not risk_out:
        return False
    escalation = str(getattr(risk_out, "escalation_level", "")).lower()
    level = str(getattr(risk_out, "overall_risk_level", "")).lower()
    return escalation in ("warning", "critical", "urgent_review", "immediate_review") or level in ("high", "critical")


def dispatch_event_chain(
    conn: Connection,
    *,
    admission_id: str,
    event_type: str,
    detail_id: str,
) -> dict[str, Any]:
    meta = _admission_meta(conn, admission_id)
    if not meta:
        return {"status": "skipped", "reason": "admission_not_found"}
    patient_id = meta["patient_id"]
    bed_id = meta["bed_id"]
    started = datetime.now(timezone.utc)
    steps: list[dict[str, Any]] = []

    def run_step(name: str, fn: Any, trigger_payload: dict[str, Any]) -> Any:
        emit_agent_lifecycle_event(
            conn,
            admission_id=admission_id,
            patient_id=patient_id,
            bed_id=bed_id,
            producer_agent=name,
            lifecycle="started",
            payload=trigger_payload,
        )
        s = datetime.now(timezone.utc)
        try:
            out = fn()
            emit_agent_lifecycle_event(
                conn,
                admission_id=admission_id,
                patient_id=patient_id,
                bed_id=bed_id,
                producer_agent=name,
                lifecycle="completed",
                payload={"trigger": event_type, "detail_id": detail_id},
            )
            steps.append({"step_name": name, "status": "ok", "started_at": s.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat()})
            return out
        except Exception as exc:
            emit_agent_lifecycle_event(
                conn,
                admission_id=admission_id,
                patient_id=patient_id,
                bed_id=bed_id,
                producer_agent=name,
                lifecycle="failed",
                payload={"error": str(exc), "trigger": event_type},
            )
            steps.append({"step_name": name, "status": "error", "error": str(exc), "started_at": s.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat()})
            return None

    bedside_out = None
    intv_out = None
    mem_out = None
    risk_out = None
    summary_out = None

    if event_type == "vital_sign":
        bedside_out = run_step(
            "bedside_monitor",
            lambda: analyze_bedside(conn, BedsideAnalyzeRequest(admission_id=admission_id, analysis_window="last_4h")),
            {"trigger": "vital_sign", "detail_id": detail_id},
        )
        mem_out = run_step(
            "patient_memory",
            lambda: evaluate_memory(conn, MemoryEvaluateRequest(admission_id=admission_id, window_hours=24)),
            {"trigger": "bedside_monitor"},
        )
        if bedside_out and bedside_out.urgency_level in ("warning", "critical"):
            risk_out = run_step(
                "risk_sentinel",
                lambda: evaluate_risk_sentinel(conn, RiskSentinelEvaluateRequest(admission_id=admission_id, max_events=200)),
                {"trigger": "bedside_urgency", "urgency": bedside_out.urgency_level},
            )
            if _risk_requires_escalation(risk_out):
                summary_out = run_step("clinical_summary", lambda: evaluate_clinical_summary(conn, admission_id), {"trigger": "risk_change"})
                run_step("ward_coordinator", lambda: evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10)), {"trigger": "risk_change"})
    elif event_type == "intervention":
        register_pending_intervention(conn, admission_id=admission_id, intervention_id=detail_id)
        intv_out = run_step(
            "intervention_tracker",
            lambda: evaluate_intervention_tracker(conn, InterventionEvaluateRequest(admission_id=admission_id, intervention_id=detail_id)),
            {"trigger": "intervention", "detail_id": detail_id},
        )
        mem_out = run_step(
            "patient_memory",
            lambda: evaluate_memory(conn, MemoryEvaluateRequest(admission_id=admission_id, window_hours=24)),
            {"trigger": "intervention_tracker"},
        )
        if intv_out and intv_out.response_assessment in ("non_responsive", "deteriorating_despite_intervention"):
            risk_out = run_step(
                "risk_sentinel",
                lambda: evaluate_risk_sentinel(conn, RiskSentinelEvaluateRequest(admission_id=admission_id, max_events=200)),
                {"trigger": "poor_intervention_response", "response": intv_out.response_assessment},
            )
            summary_out = run_step("clinical_summary", lambda: evaluate_clinical_summary(conn, admission_id), {"trigger": "intervention_deterioration"})
            run_step("ward_coordinator", lambda: evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10)), {"trigger": "intervention_deterioration"})
    elif event_type == "lab":
        mem_out = run_step(
            "patient_memory",
            lambda: evaluate_memory(conn, MemoryEvaluateRequest(admission_id=admission_id, window_hours=24)),
            {"trigger": "lab", "detail_id": detail_id},
        )
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT lab_type, abnormal_flag FROM lab_events WHERE id = %s", (detail_id,))
            lab = cur.fetchone()
        important_lab = bool(
            lab
            and (
                lab["abnormal_flag"] in ("high", "low")
                or str(lab["lab_type"]).lower() in ("lactate", "creatinine", "abg")
            )
        )
        if important_lab:
            risk_out = run_step(
                "risk_sentinel",
                lambda: evaluate_risk_sentinel(conn, RiskSentinelEvaluateRequest(admission_id=admission_id, max_events=200)),
                {"trigger": "important_lab"},
            )
            if _risk_requires_escalation(risk_out):
                summary_out = run_step("clinical_summary", lambda: evaluate_clinical_summary(conn, admission_id), {"trigger": "lab_risk_change"})
                run_step("ward_coordinator", lambda: evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10)), {"trigger": "lab_risk_change"})

    finished = datetime.now(timezone.utc)
    with conn.transaction():
        write_run_audit(
            conn,
            actor="system",
            actor_id="event_dispatcher",
            action_type="run_agent",
            target_type="event",
            target_id=detail_id,
            input_obj={"admission_id": admission_id, "event_type": event_type},
            output_obj={
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "step_count": len(steps),
                "steps": steps,
                "summary_generated": bool(summary_out),
                "memory_generated": bool(mem_out),
            },
        )
    return {"status": "ok", "step_count": len(steps), "steps": steps}
