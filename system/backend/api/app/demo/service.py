from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

import psycopg
from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.config import get_settings
from app.orchestrator.event_dispatcher import dispatch_event_chain
from app.services.agent_action_requests import fulfill_pending_requests_for_admission
from agents.ward_coordinator.schemas import WardCoordinatorEvaluateRequest
from agents.ward_coordinator.service import evaluate_ward
from app.parallel import parallel_map
from app.services.event_pipeline import write_intervention, write_lab, write_vital_sign
from app.services.ids import new_encounter_id, new_id
from app.schemas import InterventionEventCreate, LabEventCreate, VitalSignEventCreate

from llm.audit import list_llm_audit_log_ids

from .progress import emit as progress_emit, get_emit as get_progress_emit, progress_scope
from .schemas import DemoDbEffects, DemoHospitalState, DemoNextResponse, DemoRiskChange, DemoTimelineItem

SIM_TAG = "demo_auto"
SIM_STEP_MINUTES = 5
DEMO_MAX_BEDS = 10
DEMO_MIN_ACTIVE_PATIENTS = 5


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _ensure_demo_tables(conn: Connection) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_auto_state (
                    id SMALLINT PRIMARY KEY DEFAULT 1,
                    sim_time TIMESTAMPTZ NOT NULL,
                    step_index INT NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_auto_timeline (
                    id TEXT PRIMARY KEY,
                    step_index INT NOT NULL,
                    sim_time TIMESTAMPTZ NOT NULL,
                    event_type TEXT NOT NULL,
                    admission_id TEXT,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    result JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_create_state(conn: Connection) -> tuple[datetime, int]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT sim_time, step_index FROM demo_auto_state WHERE id = 1")
        row = cur.fetchone()
        if row:
            return cast(datetime, row["sim_time"]), int(row["step_index"])
    return _now_utc(), 0


def _set_state(conn: Connection, sim_time: datetime, step_index: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO demo_auto_state (id, sim_time, step_index, updated_at)
            VALUES (1, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET sim_time = EXCLUDED.sim_time, step_index = EXCLUDED.step_index, updated_at = NOW()
            """,
            (sim_time, step_index),
        )


def _counts(conn: Connection, admission_id: str | None = None) -> dict[str, int]:
    conn.row_factory = dict_row
    where = " WHERE admission_id = %s " if admission_id else ""
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table, key in [
            ("agent_outputs", "agent_outputs"),
            ("agent_events", "agent_events"),
            ("alerts", "alerts"),
            ("risk_assessments", "risks"),
        ]:
            if admission_id:
                cur.execute(f"SELECT COUNT(*) AS n FROM {table}{where}", (admission_id,))
            else:
                cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
            counts[key] = int(cur.fetchone()["n"])
    return counts


def _risk_snapshot(conn: Connection, admission_id: str | None) -> dict[str, Any]:
    if not admission_id:
        return {}
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT active_risks, care_phase, updated_at
            FROM patient_state_current
            WHERE admission_id = %s
            """,
            (admission_id,),
        )
        state = cur.fetchone()
        cur.execute(
            """
            SELECT id, timestamp, risk_type, severity, confidence, evidence, recommended_action
            FROM risk_assessments
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT 10
            """,
            (admission_id,),
        )
        risks = [_json_safe(dict(r)) for r in cur.fetchall()]
    active_risks = _json_safe(state["active_risks"]) if state else []
    severity_rank = {"low": 0, "warning": 1, "critical": 2}
    highest = "none"
    for item in active_risks or []:
        severity = str(item.get("severity") or "low")
        if highest == "none" or severity_rank.get(severity, 0) > severity_rank.get(highest, 0):
            highest = severity
    return {
        "admission_id": admission_id,
        "care_phase": state["care_phase"] if state else None,
        "active_risks": active_risks or [],
        "highest_severity": highest,
        "recent_risk_assessments": risks,
        "updated_at": _json_safe(state["updated_at"]) if state else None,
    }


def _risk_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return (
        before.get("care_phase") != after.get("care_phase")
        or before.get("highest_severity") != after.get("highest_severity")
        or before.get("active_risks") != after.get("active_risks")
        or len(before.get("recent_risk_assessments") or []) != len(after.get("recent_risk_assessments") or [])
    )


def _card_summary(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "card_id": card.get("card_id"),
        "title": card.get("title"),
        "domain": card.get("domain"),
        "card_type": card.get("card_type"),
        "allowed_use": card.get("allowed_use"),
        "human_review_required": card.get("human_review_required", True),
    }


def _knowledge_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    for key in ("knowledge_background", "knowledge_context", "medication_safety_context"):
        value = payload.get(key)
        if isinstance(value, list):
            cards.extend([c for c in value if isinstance(c, dict)])
    retrieval = payload.get("knowledge_retrieval")
    if isinstance(retrieval, dict):
        retrieved_cards = retrieval.get("retrieved_cards")
        if isinstance(retrieved_cards, list):
            cards.extend([c for c in retrieved_cards if isinstance(c, dict)])
    by_id: dict[str, dict[str, Any]] = {}
    for card in cards:
        card_id = str(card.get("card_id") or "")
        if card_id:
            by_id[card_id] = _card_summary(card)
    return {
        "used": bool(by_id) or bool(payload.get("knowledge_used")),
        "retrieved_card_ids": list(by_id.keys()),
        "retrieved_cards": list(by_id.values()),
        "background_count": len(by_id),
    }


def _agent_judgment_from_payload(agent_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    fields_by_agent = {
        "bedside_monitor": ["urgency_level", "current_status_summary", "abnormal_flags", "trend_labels", "next_action_hint", "signal_explanation"],
        "intervention_tracker": ["response_assessment", "response_label", "response_summary", "concern_flags", "urgency_level", "response_explanation", "escalation_hint"],
        "patient_memory": ["status", "short_term_summary", "active_problems", "unresolved_issues", "key_events", "memory_context_for_risk", "short_term_narrative"],
        "risk_sentinel": ["overall_risk_level", "active_risks", "new_or_worsening_flags", "recommended_next_attention", "overall_review_reminder"],
        "clinical_summary": ["urgency_level", "one_line_status", "problem_list", "active_problem_list", "watch_items", "review_reminders"],
        "ward_coordinator": [
            "ward_load_indicator",
            "priority_queue",
            "ward_overview",
            "priority_reasoning",
            "references_used",
            "next_step_plan",
            "focus_points",
            "global_watch_items",
            "review_reminders",
            "rationale",
        ],
        "compassion_family_communication": ["communication_cautions", "what_not_to_say", "requires_clinician_approval_before_delivery"],
    }
    picked: dict[str, Any] = {}
    for key in fields_by_agent.get(agent_name, []):
        if key in payload:
            picked[key] = payload[key]
    return _json_safe(picked)


def _llm_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    generated = {
        key: payload[key]
        for key in (
            "llm_explanation",
            "short_term_narrative",
            "family_plain_language_draft",
            "icu_diary_draft",
            "rationale",
            "one_line_status",
            "problem_list",
            "overall_review_reminder",
        )
        if key in payload
    }
    risks = payload.get("active_risks") or payload.get("risk_explanations")
    if risks is not None and "active_risks" not in generated:
        generated["active_risks"] = risks
    return {
        "llm_used": bool(payload.get("llm_used")),
        "fallback_used": bool(payload.get("fallback_used")),
        "audit_log_id": payload.get("audit_log_id"),
        "generated_text_fields": generated,
    }


def _fetch_agent_workflow_trace(
    conn: Connection,
    *,
    admission_id: str | None,
    since_started_at: datetime,
    include_ward_anchor: bool = True,
) -> list[dict[str, Any]]:
    if not admission_id:
        return []
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT output_id, admission_id, patient_id, bed_id, agent_name, output_type, generated_at, payload
            FROM agent_outputs
            WHERE generated_at >= %s
              AND (
                    admission_id = %s
                    OR (%s AND agent_name = 'ward_coordinator')
                  )
            ORDER BY generated_at ASC, agent_name ASC
            """,
            (since_started_at, admission_id, include_ward_anchor),
        )
        rows = [dict(r) for r in cur.fetchall()]
    trace: list[dict[str, Any]] = []
    for row in rows:
        payload = cast(dict[str, Any], row.get("payload") or {})
        trace.append(
            {
                "agent_name": row["agent_name"],
                "output_id": row["output_id"],
                "output_type": row["output_type"],
                "generated_at": _json_safe(row["generated_at"]),
                "received_context": {
                    "admission_id": row["admission_id"],
                    "patient_id": row["patient_id"],
                    "bed_id": row["bed_id"],
                },
                "knowledge": _knowledge_from_payload(payload),
                "judgment": _agent_judgment_from_payload(str(row["agent_name"]), payload),
                "llm": _llm_from_payload(payload),
                "human_review_required": bool(payload.get("human_review_required", True)),
                "forbidden_use_reminder": payload.get("forbidden_use_reminder") or payload.get("forbidden_use"),
            }
        )
    return trace


def _fetch_audit_log_ids(conn: Connection, *, admission_id: str | None, since_started_at: datetime) -> list[str]:
    if not admission_id:
        return []
    return list_llm_audit_log_ids(
        conn,
        admission_id=admission_id,
        since=since_started_at,
        limit=100,
    )


def _fetch_demo_triggered_agent_rows(
    conn: Connection, *, since_started_at: datetime, scenario_tag: str, limit: int = 400
) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT admission_id, patient_id, bed_id, producer_agent, event_type, produced_at, payload
            FROM agent_events
            WHERE produced_at >= %s
              AND admission_id IN (
                  SELECT admission_id FROM admissions WHERE scenario_tag = %s
              )
            ORDER BY produced_at DESC
            LIMIT %s
            """,
            (since_started_at, scenario_tag, limit),
        )
        return [_json_safe(dict(r)) for r in cur.fetchall()]


def _fetch_agent_workflow_trace_demo_batch(
    conn: Connection, *, since_started_at: datetime, scenario_tag: str
) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT output_id, admission_id, patient_id, bed_id, agent_name, output_type, generated_at, payload
            FROM agent_outputs
            WHERE generated_at >= %s
              AND (
                    admission_id IN (SELECT admission_id FROM admissions WHERE scenario_tag = %s)
                    OR agent_name = 'ward_coordinator'
                  )
            ORDER BY generated_at ASC, agent_name ASC
            """,
            (since_started_at, scenario_tag),
        )
        rows = [dict(r) for r in cur.fetchall()]
    trace: list[dict[str, Any]] = []
    for row in rows:
        payload = cast(dict[str, Any], row.get("payload") or {})
        trace.append(
            {
                "agent_name": row["agent_name"],
                "output_id": row["output_id"],
                "output_type": row["output_type"],
                "generated_at": _json_safe(row["generated_at"]),
                "received_context": {
                    "admission_id": row["admission_id"],
                    "patient_id": row["patient_id"],
                    "bed_id": row["bed_id"],
                },
                "knowledge": _knowledge_from_payload(payload),
                "judgment": _agent_judgment_from_payload(str(row["agent_name"]), payload),
                "llm": _llm_from_payload(payload),
                "human_review_required": bool(payload.get("human_review_required", True)),
                "forbidden_use_reminder": payload.get("forbidden_use_reminder") or payload.get("forbidden_use"),
            }
        )
    return trace


def _fetch_audit_log_ids_demo_batch(conn: Connection, *, since_started_at: datetime, scenario_tag: str, limit: int = 250) -> list[str]:
    return list_llm_audit_log_ids(
        conn,
        since=since_started_at,
        scenario_tag=scenario_tag,
        limit=limit,
    )


def _active_admissions(conn: Connection) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT admission_id, patient_id, bed_id, severity_on_admission, admit_time
            FROM admissions
            WHERE status = 'active' AND scenario_tag = %s
            ORDER BY admit_time DESC
            """,
            (SIM_TAG,),
        )
        return [dict(r) for r in cur.fetchall()]


def _seed_demo_beds(conn: Connection) -> None:
    """Pre-create DEMO_MAX_BEDS empty demo beds so admissions stay within the ward cap."""
    with conn.cursor() as cur:
        for i in range(1, DEMO_MAX_BEDS + 1):
            bid = f"demo_b_{i:02d}"
            cur.execute(
                """
                INSERT INTO beds (bed_id, bed_code, room_code, bed_type, status, notes)
                VALUES (%s, %s, 'DEMO', 'icu', 'empty', 'auto demo')
                ON CONFLICT (bed_id) DO NOTHING
                """,
                (bid, bid.upper()),
            )


def _available_demo_bed(conn: Connection, *, step_index: int, slot: int = 0) -> str:
    """Return an empty demo bed id, or allocate a new demo_b_XX id when none exist yet."""
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT bed_id FROM beds
            WHERE bed_id LIKE 'demo_b_%%' AND status = 'empty'
            ORDER BY bed_id
            LIMIT 1
            """,
        )
        row = cur.fetchone()
        if row:
            return str(row["bed_id"])
    # No demo beds yet (e.g. after seed/reset) — _create_patient_bed_admission will INSERT the bed.
    return f"demo_b_{((step_index - 1 + slot) % DEMO_MAX_BEDS) + 1:02d}"


def _create_patient_bed_admission(
    conn: Connection,
    sim_time: datetime,
    step_index: int,
    *,
    sub_tag: str = "",
    bed_id: str | None = None,
) -> dict[str, Any]:
    stem = f"{step_index:05d}{sub_tag}" if sub_tag else f"{step_index:05d}"
    pid = f"demo_p_{stem}"
    aid = f"demo_adm_{stem}"
    bid = bed_id or f"demo_b_{((step_index - 1) % DEMO_MAX_BEDS) + 1:02d}"
    sev = random.choice(["stable", "unstable", "critical"])
    encounter_id = new_encounter_id(sim_time)
    care_phase = "critical" if sev == "critical" else "stable"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO patients (patient_id, patient_code, name, gender, age, baseline_profile)
            VALUES (%s, %s, %s, %s, %s, '{}'::jsonb)
            ON CONFLICT (patient_id) DO NOTHING
            """,
            (pid, f"DP{stem}", f"Demo Patient {stem}", random.choice(["male", "female"]), random.randint(22, 88)),
        )
        cur.execute(
            """
            INSERT INTO beds (bed_id, bed_code, room_code, bed_type, status, notes)
            VALUES (%s, %s, 'DEMO', 'icu', 'empty', 'auto demo')
            ON CONFLICT (bed_id) DO NOTHING
            """,
            (bid, bid.upper()),
        )
        cur.execute("UPDATE beds SET status = 'occupied', updated_at = NOW() WHERE bed_id = %s", (bid,))
        cur.execute(
            """
            INSERT INTO admissions (
                admission_id, encounter_id, patient_id, bed_id, admission_code, admit_time, discharge_time,
                status, encounter_status, primary_diagnosis, admission_reason, severity_on_admission,
                attending_team, scenario_tag
            ) VALUES (%s, %s, %s, %s, %s, %s, NULL, 'active', 'ADMITTED', %s, %s, %s, 'DEMO_TEAM', %s)
            """,
            (
                aid,
                encounter_id,
                pid,
                bid,
                f"DEMO-{stem}",
                sim_time,
                random.choice(["sepsis", "respiratory_failure", "post_op"]),
                random.choice(["shock_workup", "hypoxemia", "post-op monitoring"]),
                sev,
                SIM_TAG,
            ),
        )
        cur.execute(
            """
            INSERT INTO patient_state_current (
                admission_id, patient_id, bed_id, current_vitals, active_problems, active_risks,
                latest_interventions, care_phase
            ) VALUES (%s, %s, %s, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, %s)
            ON CONFLICT (admission_id) DO NOTHING
            """,
            (aid, pid, bid, care_phase),
        )
    return {"admission_id": aid, "encounter_id": encounter_id, "patient_id": pid, "bed_id": bid, "severity": sev}


def _discharge_random(conn: Connection, admission: dict[str, Any], sim_time: datetime) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE admissions
            SET status = 'discharged',
                discharge_time = %s,
                encounter_status = 'DISCHARGED',
                updated_at = NOW()
            WHERE admission_id = %s
            """,
            (sim_time, admission["admission_id"]),
        )
        cur.execute("UPDATE beds SET status = 'empty', updated_at = NOW() WHERE bed_id = %s", (admission["bed_id"],))
    return {"admission_id": admission["admission_id"], "status": "discharged"}


def _clinical_discharge_candidates(conn: Connection, admissions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Conservative demo rule: discharge only stable patients without active risks."""
    if not admissions:
        return []
    conn.row_factory = dict_row
    ids = [str(a["admission_id"]) for a in admissions]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT admission_id, care_phase, active_risks
            FROM patient_state_current
            WHERE admission_id = ANY(%s::text[])
            """,
            (ids,),
        )
        states = {str(r["admission_id"]): dict(r) for r in cur.fetchall()}
    candidates: list[dict[str, Any]] = []
    for adm in admissions:
        aid = str(adm["admission_id"])
        state = states.get(aid, {})
        phase = str(state.get("care_phase") or adm.get("severity_on_admission") or "stable")
        active_risks = state.get("active_risks") or []
        if phase == "stable" and not active_risks and adm.get("severity_on_admission") != "critical":
            candidates.append(adm)
    return candidates


def _write_random_event(
    conn: Connection,
    admission: dict[str, Any],
    sim_time: datetime,
    event_type: str,
    *,
    defer_ward_coordinator: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    admission_id = str(admission["admission_id"])
    if event_type == "vital_sign":
        payload = {
            "timestamp": sim_time,
            "source": "monitor",
            "priority": random.choice(["normal", "high"]),
            "heart_rate": random.randint(70, 135),
            "mean_arterial_pressure": Decimal(str(random.randint(52, 92))),
            "respiratory_rate": random.randint(14, 34),
            "temperature": Decimal(str(round(random.uniform(36.0, 39.3), 1))),
            "spo2": Decimal(str(random.randint(86, 99))),
            "gcs": random.randint(9, 15),
        }
        body = VitalSignEventCreate(**payload)
        out = write_vital_sign(conn, admission_id, body)
        out["dispatch_result"] = dispatch_event_chain(conn, admission_id=admission_id, event_type="vital_sign", detail_id=out["detail_id"], defer_ward_coordinator=defer_ward_coordinator)
        return payload, out
    if event_type == "lab":
        lab_type = random.choice(["lactate", "creatinine", "abg", "wbc"])
        abnormal = random.choice(["normal", "high", "low"])
        payload = {
            "timestamp": sim_time,
            "source": "lab",
            "priority": "normal",
            "lab_type": lab_type,
            "value": Decimal(str(round(random.uniform(1.0, 6.0), 2))),
            "unit": "mmol/L" if lab_type == "lactate" else "unit",
            "abnormal_flag": abnormal,
        }
        body = LabEventCreate(**payload)
        out = write_lab(conn, admission_id, body)
        out["dispatch_result"] = dispatch_event_chain(conn, admission_id=admission_id, event_type="lab", detail_id=out["detail_id"], defer_ward_coordinator=defer_ward_coordinator)
        return payload, out
    payload = {
        "timestamp": sim_time,
        "source": "nurse",
        "priority": "normal",
        "intervention_type": random.choice(["fluid", "vasopressor", "ventilator_change"]),
        "description": random.choice(["fluid bolus", "norepinephrine titration", "adjust ventilator setting"]),
        "dosage": Decimal(str(round(random.uniform(0.1, 600), 2))),
        "unit": random.choice(["ml", "mcg/kg/min", "cmH2O"]),
    }
    body = InterventionEventCreate(**payload)
    out = write_intervention(conn, admission_id, body)
    out["dispatch_result"] = dispatch_event_chain(conn, admission_id=admission_id, event_type="intervention", detail_id=out["detail_id"], defer_ward_coordinator=defer_ward_coordinator)
    return payload, out




def _fulfill_pending_agent_requests_isolated(admission: dict[str, Any], sim_time: datetime) -> list[dict[str, Any]]:
    """Execute pending lab / MDT requests queued by agents (next demo step)."""
    progress_emit(
        {
            "type": "agent_requests_start",
            "admission_id": str(admission["admission_id"]),
            "bed_id": str(admission.get("bed_id") or ""),
        }
    )
    settings = get_settings()
    with psycopg.connect(settings.pg_dsn) as conn:
        with conn.transaction():
            results = fulfill_pending_requests_for_admission(
                conn, admission, sim_time=sim_time, defer_ward_coordinator=True
            )
    for item in results:
        progress_emit(
            {
                "type": "agent_request_fulfilled",
                "admission_id": item.get("admission_id"),
                "request_type": item.get("type"),
                "request_id": item.get("request_id"),
                "request": item.get("request"),
                "reason": item.get("reason"),
                "requested_by_agent": item.get("requested_by_agent"),
            }
        )
    return results


def _run_clinical_event_isolated(admission: dict[str, Any], sim_time: datetime, event_type: str) -> dict[str, Any]:
    """One patient clinical event + agent chain in its own DB connection (safe for thread pool)."""
    progress_emit(
        {
            "type": "patient_clinical_start",
            "admission_id": str(admission["admission_id"]),
            "bed_id": str(admission.get("bed_id") or ""),
            "patient_id": str(admission.get("patient_id") or ""),
            "event_type": event_type,
        }
    )
    settings = get_settings()
    with psycopg.connect(settings.pg_dsn) as conn:
        with conn.transaction():
            req, wr = _write_random_event(conn, admission, sim_time, event_type, defer_ward_coordinator=True)
    return {
        "type": event_type,
        "admission_id": str(admission["admission_id"]),
        "request_payload": _json_safe(req),
        "write_result": _json_safe(wr),
    }



def _run_ward_coordinator_batch_isolated() -> dict[str, Any]:
    """Run ward_coordinator once for the whole ICU after all per-patient work in this step."""
    progress_emit({"type": "ward_batch_start", "message": "全病房统一运行 ward_coordinator…"})
    settings = get_settings()
    started = datetime.now(timezone.utc)
    with psycopg.connect(settings.pg_dsn) as conn:
        try:
            ward_out = evaluate_ward(conn, WardCoordinatorEvaluateRequest(top_k=10))
            fin = datetime.now(timezone.utc)
            progress_emit(
                {
                    "type": "ward_batch_done",
                    "status": "ok",
                    "duration_ms": int((fin - started).total_seconds() * 1000),
                    "queue_size": len(ward_out.priority_queue),
                }
            )
            return {
                "type": "ward_coordinator_batch",
                "status": "ok",
                "ward_load_indicator": ward_out.ward_load_indicator,
                "queue_size": len(ward_out.priority_queue),
                "anchor_admission_id": ward_out.priority_queue[0].admission_id if ward_out.priority_queue else None,
                "duration_ms": int((fin - started).total_seconds() * 1000),
            }
        except Exception as exc:
            fin = datetime.now(timezone.utc)
            progress_emit(
                {
                    "type": "ward_batch_done",
                    "status": "error",
                    "duration_ms": int((fin - started).total_seconds() * 1000),
                    "error": str(exc),
                }
            )
            return {"type": "ward_coordinator_batch", "status": "error", "error": str(exc)}


def reset_demo_auto(conn: Connection) -> DemoHospitalState:
    _ensure_demo_tables(conn)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM demo_auto_timeline")
            cur.execute("DELETE FROM demo_auto_state")
            # 与 seed_test_data 一致：含 clinical_summaries / ward_priority_*，避免删 admissions 时外键冲突
            cur.execute(
                """
                TRUNCATE TABLE
                  orchestrator_runs,
                  agent_consumption_cursor,
                  agent_action_requests,
                  agent_events,
                  agent_outputs,
                  clinical_summaries,
                  ward_priority_events,
                  ward_priority_snapshots,
                  patient_memory_events,
                  patient_memory,
                  patient_state_snapshots,
                  patient_state_current,
                  intervention_pending,
                  alerts,
                  risk_assessments,
                  events,
                  intervention_events,
                  lab_events,
                  vital_sign_events,
                  audit_logs,
                  admissions,
                  beds,
                  patients
                RESTART IDENTITY CASCADE
                """
            )
            now = _now_utc()
            cur.execute(
                "INSERT INTO demo_auto_state (id, sim_time, step_index, updated_at) VALUES (1, %s, 0, NOW())",
                (now,),
            )
            _seed_demo_beds(conn)
            for i in range(DEMO_MIN_ACTIVE_PATIENTS):
                _create_patient_bed_admission(
                    conn,
                    now,
                    0,
                    sub_tag=f"r{i + 1}",
                    bed_id=f"demo_b_{i + 1:02d}",
                )
    return get_demo_state(conn)


def add_random_demo_patient(conn: Connection) -> dict[str, Any]:
    _ensure_demo_tables(conn)
    with conn.transaction():
        sim_time, step_index = _get_or_create_state(conn)
        _set_state(conn, sim_time, step_index)
        active = _active_admissions(conn)
        if len(active) >= DEMO_MAX_BEDS:
            raise HTTPException(status_code=409, detail="No empty demo ICU bed is available.")
        _seed_demo_beds(conn)
        bed = _available_demo_bed(conn, step_index=max(step_index, 1), slot=len(active))
        tag = f"m{step_index + 1}_{int(_now_utc().timestamp() * 1000)}"
        wr = _create_patient_bed_admission(conn, sim_time, step_index + 1, sub_tag=tag, bed_id=bed)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO demo_auto_timeline (id, step_index, sim_time, event_type, admission_id, payload, result, created_at)
                VALUES (%s, %s, %s, 'admission_create', %s, %s::jsonb, %s::jsonb, NOW())
                """,
                (
                    new_id("dtl"),
                    step_index,
                    sim_time,
                    wr["admission_id"],
                    Json({"manual": True, "source": "frontend_add_patient"}),
                    Json(_json_safe(wr)),
                ),
            )
    return {"admission": _json_safe(wr), "state": get_demo_state(conn)}


def discharge_demo_patient(conn: Connection, admission_id: str) -> dict[str, Any]:
    _ensure_demo_tables(conn)
    with conn.transaction():
        sim_time, step_index = _get_or_create_state(conn)
        _set_state(conn, sim_time, step_index)
        active = _active_admissions(conn)
        if len(active) <= DEMO_MIN_ACTIVE_PATIENTS:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot discharge below the demo minimum of {DEMO_MIN_ACTIVE_PATIENTS} ICU patients.",
            )
        target = next((a for a in active if str(a["admission_id"]) == admission_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Active demo admission not found.")
        wr = _discharge_random(conn, target, sim_time)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO demo_auto_timeline (id, step_index, sim_time, event_type, admission_id, payload, result, created_at)
                VALUES (%s, %s, %s, 'admission_discharge', %s, %s::jsonb, %s::jsonb, NOW())
                """,
                (
                    new_id("dtl"),
                    step_index,
                    sim_time,
                    admission_id,
                    Json({"manual": True, "source": "frontend_remove_patient"}),
                    Json(_json_safe(wr)),
                ),
            )
    return {"discharge": _json_safe(wr), "state": get_demo_state(conn)}


def get_demo_state(conn: Connection) -> DemoHospitalState:
    _ensure_demo_tables(conn)
    sim_time, step_index = _get_or_create_state(conn)
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM admissions WHERE status = 'active' AND scenario_tag = %s", (SIM_TAG,))
        active = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM beds WHERE status = 'occupied'")
        occupied = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM patients")
        total_patients = int(cur.fetchone()["n"])
        cur.execute(
            """
            SELECT id, step_index, sim_time, event_type, admission_id, payload, result, created_at
            FROM demo_auto_timeline ORDER BY step_index DESC LIMIT 10
            """
        )
        timeline = [dict(r) for r in cur.fetchall()]
    return DemoHospitalState(
        sim_time=sim_time,
        step_index=step_index,
        active_admissions=active,
        occupied_beds=occupied,
        total_patients=total_patients,
        recent_events=timeline,
    )


def list_timeline(conn: Connection, limit: int = 100) -> list[DemoTimelineItem]:
    _ensure_demo_tables(conn)
    limit = max(1, min(limit, 500))
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, step_index, sim_time, event_type, admission_id, payload, result, created_at
            FROM demo_auto_timeline ORDER BY step_index DESC LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    items: list[DemoTimelineItem] = []
    for r in rows:
        row = dict(r)
        row["payload"] = row.get("payload") or {}
        row["result"] = row.get("result") or {}
        items.append(DemoTimelineItem(**row))
    return items


def next_demo_step(conn: Connection) -> DemoNextResponse:
    """Advance simulation by SIM_STEP_MINUTES with a **ward batch tick**.

    Each tick may include:
    1. Batch discharge/admit (all admissions for this tick finish before any agents run).
    2. Parallel fulfill pending lab/MDT requests per patient (patient-level agents only).
    3. Parallel clinical event + per-patient agent chain (ward_coordinator deferred).
    4. Single ward_coordinator evaluation for the whole ICU.
    Ward capacity is capped at **DEMO_MAX_BEDS** (10) demo beds (`demo_b_01` … `demo_b_10`),
    with at least **DEMO_MIN_ACTIVE_PATIENTS** active ICU patients after every tick.
    """
    _ensure_demo_tables(conn)
    step_wall_started_at = datetime.now(timezone.utc)

    # Phase 1: discharge / admit / advance sim clock — must commit before parallel workers see rows.
    with conn.transaction():
        sim_before, prev_index = _get_or_create_state(conn)
        if prev_index == 0:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO demo_auto_state (id, sim_time, step_index, updated_at)
                    VALUES (1, %s, 0, NOW())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (sim_before,),
                )
        sim_after = sim_before + timedelta(minutes=SIM_STEP_MINUTES)
        step_index = prev_index + 1
        before_all = _counts(conn)
        _seed_demo_beds(conn)

        active_start = _active_admissions(conn)
        progress_emit(
            {
                "type": "step_plan",
                "sim_before": sim_before.isoformat(),
                "sim_after": sim_after.isoformat(),
                "step_index": step_index,
                "active_patients": len(active_start),
            }
        )
        progress_emit({"type": "phase", "message": "更新仿真时钟与出入院…"})
        anchor_before = active_start[0]["admission_id"] if active_start else None
        risk_before = _risk_snapshot(conn, anchor_before) if anchor_before else {}

        sub_events: list[dict[str, Any]] = []
        discharged_ids: list[str] = []

        discharge_candidates = _clinical_discharge_candidates(conn, active_start)
        safe_discharge_room = max(0, len(active_start) - DEMO_MIN_ACTIVE_PATIENTS)
        max_dis = min(2, safe_discharge_room, len(discharge_candidates))
        nd = random.randint(0, max_dis) if max_dis > 0 else 0
        for _ in range(nd):
            active_now = _active_admissions(conn)
            candidate_ids = {str(a["admission_id"]) for a in _clinical_discharge_candidates(conn, active_now)}
            pool = [
                a
                for a in active_now
                if a["admission_id"] not in discharged_ids and str(a["admission_id"]) in candidate_ids
            ]
            if not pool:
                break
            tgt = random.choice(pool)
            discharged_ids.append(cast(str, tgt["admission_id"]))
            wr = _discharge_random(conn, tgt, sim_after)
            sub_events.append({
                "type": "admission_discharge",
                "admission_id": tgt["admission_id"],
                "reason": "clinical_stable_no_active_risks",
                "write_result": _json_safe(wr),
            })

        active_after_dis = _active_admissions(conn)
        admit_slots = max(0, DEMO_MAX_BEDS - len(active_after_dis))
        needed_min = max(0, DEMO_MIN_ACTIVE_PATIENTS - len(active_after_dis))
        na = max(needed_min, random.randint(0, 2))
        na = min(na, admit_slots)
        for k in range(na):
            bed = _available_demo_bed(conn, step_index=step_index, slot=k)
            sub_tag = f"a{k + 1}"
            wr = _create_patient_bed_admission(conn, sim_after, step_index, sub_tag=sub_tag, bed_id=bed)
            sub_events.append({"type": "admission_create", "admission_id": wr["admission_id"], "write_result": _json_safe(wr)})

        if sub_events or na or discharged_ids:
            sub_events.append({
                "type": "admissions_batch_complete",
                "admissions_created": na,
                "discharges": len(discharged_ids),
                "active_count": len(_active_admissions(conn)),
            })

        _set_state(conn, sim_after, step_index)

    progress_emit(
        {
            "type": "phase",
            "message": f"出入院已提交：出院 {len(discharged_ids)} 人，新收治 {na} 人；仿真时间 → {sim_after.isoformat()}",
        }
    )

    event_type = "batch_step"
    active_clinical = _active_admissions(conn)

    progress_emit(
        {
            "type": "phase",
            "message": f"阶段 2/4：并行履约 {len(active_clinical)} 位患者的 Agent 待办（检查/会诊）…",
        }
    )
    request_jobs = [(adm, sim_after) for adm in active_clinical]
    captured_emit_req = get_progress_emit()

    def _request_job(job: tuple[dict[str, Any], datetime]) -> list[dict[str, Any]]:
        adm, sim_t = job
        if captured_emit_req:
            with progress_scope(captured_emit_req):
                return _fulfill_pending_agent_requests_isolated(adm, sim_t)
        return _fulfill_pending_agent_requests_isolated(adm, sim_t)

    request_fulfillment: list[dict[str, Any]] = []
    for chunk in parallel_map(request_jobs, _request_job):
        if isinstance(chunk, list):
            request_fulfillment.extend(chunk)
    if request_fulfillment:
        sub_events.extend(request_fulfillment)

    random.shuffle(active_clinical)
    clinical_jobs: list[tuple[dict[str, Any], datetime, list[str]]] = []
    for adm in active_clinical:
        event_types = ["vital_sign"]
        if random.random() < 0.35:
            event_types.append("lab")
        if random.random() < 0.30:
            event_types.append("intervention")
        clinical_jobs.append((adm, sim_after, event_types))

    progress_emit(
        {
            "type": "phase",
            "message": f"阶段 3/4：为 {len(active_clinical)} 位在院患者写入新体征，并按需追加检验/干预事件后运行患者级 Agent 链…",
        }
    )

    captured_emit = get_progress_emit()

    def _clinical_job(job: tuple[dict[str, Any], datetime, list[str]]) -> list[dict[str, Any]]:
        adm, sim_t, event_types = job
        events: list[dict[str, Any]] = []
        for et in event_types:
            if captured_emit:
                with progress_scope(captured_emit):
                    events.append(_run_clinical_event_isolated(adm, sim_t, et))
            else:
                events.append(_run_clinical_event_isolated(adm, sim_t, et))
        return events

    for patient_events in parallel_map(clinical_jobs, _clinical_job):
        sub_events.extend(patient_events)

    progress_emit({"type": "phase", "message": "阶段 4/4：全病房统一运行 ward_coordinator…"})
    ward_sub = _run_ward_coordinator_batch_isolated()
    sub_events.append(ward_sub)

    with conn.transaction():
        active_end = _active_admissions(conn)
        anchor_after: str | None = None
        if anchor_before and any(cast(str, a["admission_id"]) == anchor_before for a in active_end):
            anchor_after = anchor_before
        elif active_end:
            anchor_after = cast(str, active_end[0]["admission_id"])
        else:
            anchor_after = None

        admission_id = anchor_after
        request_payload: dict[str, Any] = {"batch": True, "sub_events": sub_events}
        write_result: dict[str, Any] = {
            "batch": True,
            "sub_event_count": len(sub_events),
            "sub_events": sub_events,
        }

        triggered_agents = _fetch_demo_triggered_agent_rows(
            conn, since_started_at=step_wall_started_at, scenario_tag=SIM_TAG, limit=500
        )
        after_all = _counts(conn)
        risk_after = _risk_snapshot(conn, anchor_after) if anchor_after else {}
        risk_change = DemoRiskChange(
            before=risk_before,
            after=risk_after,
            changed=_risk_changed(risk_before, risk_after),
        )
        workflow_trace = _fetch_agent_workflow_trace_demo_batch(
            conn, since_started_at=step_wall_started_at, scenario_tag=SIM_TAG
        )
        audit_log_ids = _fetch_audit_log_ids_demo_batch(conn, since_started_at=step_wall_started_at, scenario_tag=SIM_TAG)
        effects = DemoDbEffects(
            agent_outputs_added=after_all["agent_outputs"] - before_all["agent_outputs"],
            agent_events_added=after_all["agent_events"] - before_all["agent_events"],
            alerts_added=after_all["alerts"] - before_all["alerts"],
            risks_added=after_all["risks"] - before_all["risks"],
        )
        delta = {
            "event_type": event_type,
            "admission_id": admission_id,
            "sub_event_count": len(sub_events),
            "sub_event_types": [str(s.get("type")) for s in sub_events],
            "triggered_agent_names": sorted({str(a["producer_agent"]) for a in triggered_agents}),
            "triggered_event_types": sorted({str(a["event_type"]) for a in triggered_agents}),
            "agent_output_names": [str(item["agent_name"]) for item in workflow_trace],
            "risk_changed": risk_change.changed,
            "risk_before": risk_change.before.get("highest_severity"),
            "risk_after": risk_change.after.get("highest_severity"),
            "llm_used_by": [str(item["agent_name"]) for item in workflow_trace if item.get("llm", {}).get("llm_used")],
            "fallback_used_by": [str(item["agent_name"]) for item in workflow_trace if item.get("llm", {}).get("fallback_used")],
            "knowledge_cards_read": sorted(
                {
                    str(card_id)
                    for item in workflow_trace
                    for card_id in item.get("knowledge", {}).get("retrieved_card_ids", [])
                }
            ),
        }
        full_log = {
            "step_index": step_index,
            "sim_time_before": sim_before.isoformat(),
            "sim_time_after": sim_after.isoformat(),
            "event": {
                "event_type": event_type,
                "admission_id": admission_id,
                "request_payload": _json_safe(request_payload),
                "write_result": _json_safe(write_result),
            },
            "db_effects": effects.model_dump(mode="json"),
            "risk_change": risk_change.model_dump(mode="json"),
            "agent_workflow_trace": workflow_trace,
            "audit_log_ids": audit_log_ids,
            "human_review_required": True,
        }
        resp = DemoNextResponse(
            step_index=step_index,
            sim_time_before=sim_before,
            sim_time_after=sim_after,
            event_type=cast(Any, event_type),
            admission_id=admission_id,
            event_request_payload=_json_safe(request_payload),
            event_write_result=_json_safe(write_result),
            triggered_agents=triggered_agents,
            db_effects=effects,
            agent_delta_summary=delta,
            risk_change=risk_change,
            agent_workflow_trace=workflow_trace,
            audit_log_ids=audit_log_ids,
            full_observability_log=full_log,
        )
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO demo_auto_timeline (id, step_index, sim_time, event_type, admission_id, payload, result, created_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, NOW())
            """,
            (
                new_id("dtl"),
                step_index,
                sim_after,
                event_type,
                admission_id,
                Json(_json_safe(request_payload)),
                Json(_json_safe(resp.model_dump(mode="python"))),
            ),
        )
        cur.close()
    progress_emit({"type": "complete", "step_index": step_index})
    return resp
