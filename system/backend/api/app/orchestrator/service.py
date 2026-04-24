from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.ids import new_id
from agents.bedside_monitor.schemas import BedsideAnalyzeRequest
from agents.bedside_monitor.service import analyze_bedside
from agents.intervention_tracker.schemas import InterventionEvaluateRequest
from agents.intervention_tracker.service import evaluate_intervention_tracker
from agents.patient_memory.schemas import MemoryEvaluateRequest
from agents.patient_memory.service import evaluate_memory
from agents.risk_sentinel.schemas import RiskSentinelEvaluateRequest
from agents.risk_sentinel.service import evaluate_risk_sentinel
from agents.clinical_summary.service import evaluate_clinical_summary
from agents.ward_coordinator.schemas import WardCoordinatorEvaluateRequest
from agents.ward_coordinator.service import evaluate_ward
from app.services.agent_observability import emit_agent_lifecycle_event

from .schemas import DemoRunRequest, DemoRunResponse, StepResult


def _active_admissions(conn: Connection) -> list[str]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT admission_id FROM admissions WHERE status = 'active' ORDER BY admit_time DESC")
        return [r["admission_id"] for r in cur.fetchall()]


def _latest_intervention_id(conn: Connection, admission_id: str) -> str | None:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM intervention_events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (admission_id,),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def _admission_meta(conn: Connection, admission_id: str) -> tuple[str, str] | None:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT patient_id, bed_id FROM admissions WHERE admission_id = %s", (admission_id,))
        row = cur.fetchone()
        if not row:
            return None
        return row["patient_id"], row["bed_id"]


def run_demo_pipeline(conn: Connection, req: DemoRunRequest) -> DemoRunResponse:
    if req.run_all_active:
        admissions = _active_admissions(conn)
    elif req.admission_id:
        admissions = [req.admission_id]
    else:
        raise HTTPException(status_code=422, detail="Provide admission_id or set run_all_active=true")

    if not admissions:
        raise HTTPException(status_code=404, detail="No active admissions")

    run_id = new_id("run")
    started = datetime.now(timezone.utc)
    steps: list[StepResult] = []

    for admission_id in admissions:
        meta = _admission_meta(conn, admission_id)
        if not meta:
            continue
        patient_id, bed_id = meta
        s = datetime.now(timezone.utc)
        emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="bedside_monitor", lifecycle="started", payload={"trigger": "demo-run"})
        try:
            bedside_out = analyze_bedside(conn, BedsideAnalyzeRequest(admission_id=admission_id, analysis_window="last_4h"))
            status = "ok"
            detail = {"urgency_level": bedside_out.urgency_level}
            emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="bedside_monitor", lifecycle="completed", payload=detail)
            err_class = None
        except Exception as exc:
            status = "error"
            detail = {"error": str(exc)}
            emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="bedside_monitor", lifecycle="failed", payload=detail)
            err_class = exc.__class__.__name__
        steps.append(StepResult(step_name="bedside_monitor", admission_id=admission_id, status=status, started_at=s, finished_at=datetime.now(timezone.utc), detail=detail, input_sources=["vital_sign_events"], input_window="last_4h", output_id=None, error_class=err_class, retry_count=0))

        intv_id = _latest_intervention_id(conn, admission_id)
        s = datetime.now(timezone.utc)
        if not intv_id:
            steps.append(StepResult(step_name="intervention_tracker", admission_id=admission_id, status="skipped", started_at=s, finished_at=datetime.now(timezone.utc), detail={"reason": "no_intervention"}, input_sources=["intervention_events", "vital_sign_events"], input_window="pre/post window", output_id=None, error_class=None, retry_count=0))
        else:
            emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="intervention_tracker", lifecycle="started", payload={"intervention_id": intv_id})
            try:
                intv_out = evaluate_intervention_tracker(conn, InterventionEvaluateRequest(admission_id=admission_id, intervention_id=intv_id))
                status = "ok"
                detail = {"response_assessment": intv_out.response_assessment}
                emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="intervention_tracker", lifecycle="completed", payload=detail)
                err_class = None
            except Exception as exc:
                status = "error"
                detail = {"error": str(exc)}
                emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="intervention_tracker", lifecycle="failed", payload=detail)
                err_class = exc.__class__.__name__
            steps.append(StepResult(step_name="intervention_tracker", admission_id=admission_id, status=status, started_at=s, finished_at=datetime.now(timezone.utc), detail=detail, input_sources=["intervention_events", "vital_sign_events"], input_window="pre/post window", output_id=None, error_class=err_class, retry_count=0))

        s = datetime.now(timezone.utc)
        emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="patient_memory", lifecycle="started", payload={"window_hours": req.memory_window_hours})
        try:
            mem_out = evaluate_memory(conn, MemoryEvaluateRequest(admission_id=admission_id, window_hours=req.memory_window_hours))
            status = "ok"
            detail = {"data_completeness_ratio": mem_out.data_completeness_ratio}
            emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="patient_memory", lifecycle="completed", payload=detail)
            err_class = None
        except Exception as exc:
            status = "error"
            detail = {"error": str(exc)}
            emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="patient_memory", lifecycle="failed", payload=detail)
            err_class = exc.__class__.__name__
        steps.append(StepResult(step_name="patient_memory", admission_id=admission_id, status=status, started_at=s, finished_at=datetime.now(timezone.utc), detail=detail, input_sources=["vital_sign_events", "lab_events", "intervention_events"], input_window=f"last_{req.memory_window_hours}h", output_id=None, error_class=err_class, retry_count=0))

        s = datetime.now(timezone.utc)
        emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="risk_sentinel", lifecycle="started", payload={"max_events": 200})
        try:
            risk_out = evaluate_risk_sentinel(conn, RiskSentinelEvaluateRequest(admission_id=admission_id, max_events=200))
            status = "ok"
            detail = {"risk_count": len(risk_out.risks), "escalation_level": risk_out.escalation_level}
            emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="risk_sentinel", lifecycle="completed", payload=detail)
            err_class = None
        except Exception as exc:
            status = "error"
            detail = {"error": str(exc)}
            emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="risk_sentinel", lifecycle="failed", payload=detail)
            err_class = exc.__class__.__name__
        steps.append(StepResult(step_name="risk_sentinel", admission_id=admission_id, status=status, started_at=s, finished_at=datetime.now(timezone.utc), detail=detail, input_sources=["agent_events", "agent_outputs"], input_window="incremental_cursor", output_id=None, error_class=err_class, retry_count=0))

        s = datetime.now(timezone.utc)
        emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="clinical_summary", lifecycle="started", payload={"mode": "demo-run"})
        try:
            summary_out = evaluate_clinical_summary(conn, admission_id)
            status = "ok"
            detail = {"problem_count": len(summary_out.problem_list)}
            emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="clinical_summary", lifecycle="completed", payload=detail)
            err_class = None
        except Exception as exc:
            status = "error"
            detail = {"error": str(exc)}
            emit_agent_lifecycle_event(conn, admission_id=admission_id, patient_id=patient_id, bed_id=bed_id, producer_agent="clinical_summary", lifecycle="failed", payload=detail)
            err_class = exc.__class__.__name__
        steps.append(StepResult(step_name="clinical_summary", admission_id=admission_id, status=status, started_at=s, finished_at=datetime.now(timezone.utc), detail=detail, input_sources=["agent_outputs", "risk_assessments", "admissions"], input_window="latest", output_id=None, error_class=err_class, retry_count=0))

    s = datetime.now(timezone.utc)
    try:
        ward_out = evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=req.top_k))
        status = "ok"
        detail = {"queue_size": len(ward_out.priority_queue), "ward_load_indicator": ward_out.ward_load_indicator}
        err_class = None
    except Exception as exc:
        status = "error"
        detail = {"error": str(exc)}
        err_class = exc.__class__.__name__
    steps.append(StepResult(step_name="ward_coordinator", admission_id="global", status=status, started_at=s, finished_at=datetime.now(timezone.utc), detail=detail, input_sources=["patient_state_current", "alerts"], input_window="latest", output_id=None, error_class=err_class, retry_count=0))

    finished = datetime.now(timezone.utc)

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orchestrator_runs (run_id, started_at, finished_at, target_admissions, step_results)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (run_id, started, finished, Json(admissions), Json([s.model_dump(mode="json") for s in steps])),
            )
            cur.execute(
                """
                INSERT INTO audit_logs (id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output)
                VALUES (%s, %s, 'system', 'orchestrator', 'run_agent', 'orchestrator_run', %s, %s::jsonb, %s::jsonb)
                """,
                (new_id("log"), finished, run_id, Json(req.model_dump()), Json({"step_count": len(steps), "steps": [s.model_dump(mode="json") for s in steps]})),
            )

    return DemoRunResponse(run_id=run_id, started_at=started, finished_at=finished, target_admissions=admissions, step_results=steps)
