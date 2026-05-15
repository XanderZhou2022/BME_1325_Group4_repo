from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.ids import new_id
from knowledge.retriever import retrieve_cards
from .rules import run_intervention_tracker
from .schemas import AssessmentWindow, InterventionEvaluateRequest, InterventionEvaluateResponse, InterventionType, MetricChange, VitalPoint


DEFAULT_PRE_WINDOW_MINUTES = 60
DEFAULT_POST_WINDOW_MINUTES = 60
DEFAULT_NOTIFY_AGENTS = ["patient_memory", "risk_sentinel"]
INTV_REMINDER = [
    "Do not use this output to adjust dose.",
    "Do not use this output as a treatment plan.",
    "Clinician review is required.",
]


def _window_profile(intervention_type: InterventionType) -> tuple[int, int, list[int]]:
    if intervention_type in ("fluid", "fluid_bolus"):
        return 30, 60, [15, 30, 60]
    if intervention_type in ("vasopressor", "vasopressor_adjustment"):
        return 30, 60, [10, 30, 60]
    if intervention_type in ("ventilator_change", "ventilator_adjustment"):
        return 30, 120, [15, 60, 120]
    if intervention_type == "antibiotic_start":
        return 360, 1440, [360, 720, 1440]
    return DEFAULT_PRE_WINDOW_MINUTES, DEFAULT_POST_WINDOW_MINUTES, [DEFAULT_POST_WINDOW_MINUTES]


def _ensure_pending_table(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS intervention_pending (
                id TEXT PRIMARY KEY,
                admission_id TEXT NOT NULL REFERENCES admissions(admission_id),
                intervention_id TEXT NOT NULL UNIQUE REFERENCES intervention_events(id),
                status TEXT NOT NULL CHECK (status IN ('pending', 'ready_for_evaluation', 'completed', 'insufficient_data', 'expired')),
                observation_end_at TIMESTAMPTZ NOT NULL,
                last_evaluated_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute("ALTER TABLE intervention_pending ADD COLUMN IF NOT EXISTS checkpoint_offsets_minutes JSONB NOT NULL DEFAULT '[]'::jsonb")
        cur.execute("ALTER TABLE intervention_pending ADD COLUMN IF NOT EXISTS next_checkpoint_at TIMESTAMPTZ")


def _intervention_knowledge_context(
    *,
    patient_id: str,
    bed_id: str,
    intervention_type: str,
    response_label: str,
    concern_flags: list[str],
) -> dict[str, Any]:
    signals = [intervention_type, response_label] + concern_flags
    retrieval = retrieve_cards(
        "intervention_tracker",
        {"patient_id": patient_id, "bed_id": bed_id},
        trigger_signals=signals,
        query=" ".join(signals),
    )
    cards = retrieval["retrieved_cards"]
    medication_cards = [c for c in cards if c.get("domain") == "medication_safety"]
    explanation = (
        "The structured response assessment suggests limited or concerning response after the documented intervention. "
        "Retrieved knowledge cards provide background for clinician review only, not treatment or dose adjustment guidance."
        if response_label in ("partially_responsive", "non_responsive", "deteriorating_despite_intervention")
        else "The structured intervention response assessment is provided for clinician review and should not be used as a treatment plan."
    )
    return {
        "knowledge_background": cards,
        "response_explanation": explanation,
        "medication_safety_context": medication_cards,
        "forbidden_use_reminder": INTV_REMINDER,
        "knowledge_used": bool(cards),
        "llm_used": False,
        "fallback_used": False,
        "audit_log_id": None,
        "human_review_required": True,
    }


def register_pending_intervention(conn: Connection, *, admission_id: str, intervention_id: str) -> None:
    _ensure_pending_table(conn)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT timestamp FROM intervention_events WHERE id = %s AND admission_id = %s",
            (intervention_id, admission_id),
        )
        row = cur.fetchone()
        if not row:
            return
        with conn.cursor(row_factory=dict_row) as c2:
            c2.execute("SELECT intervention_type FROM intervention_events WHERE id = %s", (intervention_id,))
            itype_row = c2.fetchone()
        intervention_type = cast(InterventionType, (itype_row["intervention_type"] if itype_row else "fluid"))
        _, post_minutes, checkpoints = _window_profile(intervention_type)
        observation_end_at = cast(datetime, row["timestamp"]) + timedelta(minutes=post_minutes)
        next_checkpoint_at = cast(datetime, row["timestamp"]) + timedelta(minutes=checkpoints[0])
        cur.execute(
            """
            INSERT INTO intervention_pending (id, admission_id, intervention_id, status, observation_end_at, checkpoint_offsets_minutes, next_checkpoint_at)
            VALUES (%s, %s, %s, 'pending', %s, %s::jsonb, %s)
            ON CONFLICT (intervention_id) DO UPDATE SET
                status = 'pending',
                observation_end_at = EXCLUDED.observation_end_at,
                checkpoint_offsets_minutes = EXCLUDED.checkpoint_offsets_minutes,
                next_checkpoint_at = EXCLUDED.next_checkpoint_at,
                updated_at = NOW()
            """,
            (new_id("pend"), admission_id, intervention_id, observation_end_at, Json(checkpoints), next_checkpoint_at),
        )


def evaluate_due_pending_interventions(conn: Connection, *, limit: int = 100) -> int:
    _ensure_pending_table(conn)
    now = datetime.now(timezone.utc)
    count = 0
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT admission_id, intervention_id
            FROM intervention_pending
            WHERE status IN ('pending', 'ready_for_evaluation', 'insufficient_data')
              AND (
                    (next_checkpoint_at IS NOT NULL AND next_checkpoint_at <= %s)
                    OR
                    (next_checkpoint_at IS NULL AND observation_end_at <= %s)
                  )
            ORDER BY COALESCE(next_checkpoint_at, observation_end_at) ASC
            LIMIT %s
            """,
            (now, now, limit),
        )
        rows = cur.fetchall()
    for row in rows:
        evaluate_intervention_tracker(
            conn,
            InterventionEvaluateRequest(
                admission_id=row["admission_id"],
                intervention_id=row["intervention_id"],
            ),
        )
        count += 1
    return count


def evaluate_intervention_tracker(conn: Connection, req: InterventionEvaluateRequest) -> InterventionEvaluateResponse:
    _ensure_pending_table(conn)
    # --- admission (patient/bed) ---
    with conn.cursor() as cur:
        cur.row_factory = dict_row
        cur.execute(
            "SELECT patient_id, bed_id FROM admissions WHERE admission_id = %s",
            (req.admission_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Admission not found")
    patient_id = cast(str, row["patient_id"])
    bed_id = cast(str, row["bed_id"])

    # --- intervention (time/type) ---
    with conn.cursor() as cur:
        cur.row_factory = dict_row
        cur.execute(
            """
            SELECT id, timestamp, intervention_type
            FROM intervention_events
            WHERE admission_id = %s AND id = %s
            """,
            (req.admission_id, req.intervention_id),
        )
        intv = cur.fetchone()
    if not intv:
        raise HTTPException(status_code=404, detail="Intervention event not found")

    intervention_time = cast(datetime, intv["timestamp"])
    intervention_type = cast(InterventionType, intv["intervention_type"])

    prof_pre, prof_post, checkpoints = _window_profile(intervention_type)
    pre_window_minutes = req.pre_window_minutes or prof_pre
    if req.post_window_minutes is not None:
        post_window_minutes = req.post_window_minutes
    elif req.expected_observation_window_minutes is not None:
        post_window_minutes = req.expected_observation_window_minutes
    else:
        post_window_minutes = prof_post

    pre_start = intervention_time - timedelta(minutes=pre_window_minutes)
    post_end = intervention_time + timedelta(minutes=post_window_minutes)

    # --- vitals slice ---
    vitals: list[VitalPoint] = []
    with conn.cursor() as cur:
        cur.row_factory = dict_row
        cur.execute(
            """
            SELECT timestamp,
                   heart_rate,
                   mean_arterial_pressure,
                   spo2,
                   respiratory_rate,
                   temperature,
                   fio2,
                   NULL::numeric AS peep
            FROM vital_sign_events
            WHERE admission_id = %s
              AND timestamp >= %s
              AND timestamp <= %s
            ORDER BY timestamp ASC
            """,
            (req.admission_id, pre_start, post_end),
        )
        rows = cur.fetchall()

    for r in rows:
        vitals.append(
            VitalPoint(
                timestamp=r["timestamp"],
                heart_rate=float(r["heart_rate"]) if r["heart_rate"] is not None else None,
                mean_arterial_pressure=float(r["mean_arterial_pressure"]) if r["mean_arterial_pressure"] is not None else None,
                spo2=float(r["spo2"]) if r["spo2"] is not None else None,
                respiratory_rate=float(r["respiratory_rate"]) if r["respiratory_rate"] is not None else None,
                temperature=float(r["temperature"]) if r["temperature"] is not None else None,
                fio2=float(r["fio2"]) if r["fio2"] is not None else None,
                peep=float(r["peep"]) if r["peep"] is not None else None,
            )
        )

    pre_vitals = [v for v in vitals if v.timestamp <= intervention_time]
    post_vitals = [v for v in vitals if v.timestamp > intervention_time]

    observation_window = f"pre {pre_window_minutes}m / post {post_window_minutes}m"
    if not post_vitals and intervention_type != "antibiotic_start":
        result = {
            "response_assessment": "not_enough_data",
            "response_label": "not_enough_data",
            "target_metrics": {},
            "before_after_comparison": {},
            "evidence": [{"reason": "no_post_intervention_vitals"}],
            "escalation_hint": "await observation window completion",
            "canonical_intervention_type": intervention_type,
        }
    else:
        result = run_intervention_tracker(
            intervention_type=intervention_type,
            intervention_time=intervention_time,
            pre_vitals=pre_vitals,
            post_vitals=post_vitals,
            observation_window=observation_window,
        )
    response_assessment = cast(str, result["response_assessment"])
    response_label = cast(str, result.get("response_label", response_assessment))
    generated_at = datetime.now(timezone.utc)
    urgency_level = "critical" if response_label == "deteriorating_despite_intervention" else ("warning" if response_label in ("partially_responsive", "non_responsive") else "info")
    concern_flags: list[str] = []
    if response_label == "deteriorating_despite_intervention":
        concern_flags.append("deteriorating_despite_intervention")
    elif response_label == "non_responsive":
        concern_flags.append("persistent_non_response")
    elif response_label == "not_enough_data":
        concern_flags.append("insufficient_post_intervention_data")
    response_summary = (
        "Intervention followed by expected improvement."
        if response_label == "responsive"
        else "Intervention followed by partial improvement but not at target."
        if response_label == "partially_responsive"
        else "No meaningful response observed after intervention."
        if response_label == "non_responsive"
        else "Physiology deteriorated despite intervention."
        if response_label == "deteriorating_despite_intervention"
        else "Not enough post-intervention data for reliable assessment."
    )
    key_changes: list[MetricChange] = []
    ba = cast(dict[str, Any], result.get("before_after_comparison") or {})
    if "pre_mean" in ba and "post_mean" in ba:
        key_changes.append(
            MetricChange(
                metric="mean_arterial_pressure",
                before=f"{ba.get('pre_mean')}",
                after=f"{ba.get('post_mean')}",
                interpretation=f"delta={ba.get('delta')}",
            )
        )
    if "delta_spo2" in ba:
        key_changes.append(
            MetricChange(
                metric="spo2",
                before="pre_window",
                after="post_window",
                interpretation=f"delta={ba.get('delta_spo2')}",
            )
        )
    payload = {
        "schema_version": "intervention_tracker.v1.1",
        "agent": "intervention_tracker",
        "admission_id": req.admission_id,
        "intervention_id": req.intervention_id,
        "intervention_type": intervention_type,
        "intervention_time": intervention_time.isoformat(),
        "assessment_window": {
            "pre_window": f"{pre_window_minutes}min before intervention",
            "post_window": f"{post_window_minutes}min after intervention",
        },
        "response_label": response_label,
        "response_summary": response_summary,
        "key_changes": [k.model_dump(mode="json") for k in key_changes],
        "concern_flags": concern_flags,
        "urgency_level": urgency_level,
        "notify_agents": DEFAULT_NOTIFY_AGENTS,
        "observation_window": observation_window,
        "response_assessment": response_assessment,
        "target_metrics": result["target_metrics"],
        "before_after_comparison": result["before_after_comparison"],
        "evidence": result["evidence"],
        "escalation_hint": result["escalation_hint"],
        "generated_at": generated_at.isoformat(),
    }
    kctx = _intervention_knowledge_context(
        patient_id=patient_id,
        bed_id=bed_id,
        intervention_type=str(intervention_type),
        response_label=response_label,
        concern_flags=concern_flags,
    )
    payload.update(kctx)

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'intervention_tracker', 'intervention_tracker.started', 'v1', %s, NULL, %s::jsonb)
                """,
                (new_id("aevt"), req.admission_id, patient_id, bed_id, generated_at, Json({"intervention_id": req.intervention_id})),
            )
            cur.execute(
                """
                INSERT INTO agent_registry (agent_name, input_event_types, output_event_type, schema_version, enabled)
                VALUES ('intervention_tracker', '["intervention"]'::jsonb, 'intervention_evaluation_ready', 'v1', TRUE)
                ON CONFLICT (agent_name) DO UPDATE SET enabled = TRUE, updated_at = NOW()
                """
            )
            output_id = new_id("out")
            event_id = new_id("aevt")
            output_event = "intervention_evaluation_ready" if response_label != "not_enough_data" else "intervention_evaluation_pending"
            cur.execute(
                """
                INSERT INTO agent_outputs (
                    output_id, admission_id, patient_id, bed_id, agent_name,
                    schema_version, output_type, generated_at, payload
                ) VALUES (%s, %s, %s, %s, 'intervention_tracker', 'v1', %s, %s, %s::jsonb)
                """,
                (output_id, req.admission_id, patient_id, bed_id, output_event, generated_at, Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'intervention_tracker', %s, 'v1', %s, %s, %s::jsonb)
                """,
                (event_id, req.admission_id, patient_id, bed_id, output_event, generated_at, output_id, Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO intervention_pending (id, admission_id, intervention_id, status, observation_end_at, last_evaluated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (intervention_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    last_evaluated_at = NOW(),
                    next_checkpoint_at = CASE
                        WHEN intervention_pending.next_checkpoint_at IS NULL THEN EXCLUDED.observation_end_at
                        WHEN intervention_pending.next_checkpoint_at > NOW() THEN intervention_pending.next_checkpoint_at
                        ELSE NOW() + INTERVAL '10 minutes'
                    END,
                    updated_at = NOW()
                """,
                (
                    new_id("pend"),
                    req.admission_id,
                    req.intervention_id,
                    "insufficient_data" if response_label == "not_enough_data" else "completed",
                    post_end,
                ),
            )
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'intervention_tracker', %s, 'v1', %s, %s, %s::jsonb)
                """,
                (
                    new_id("aevt"),
                    req.admission_id,
                    patient_id,
                    bed_id,
                    "intervention_tracker.pending" if response_label == "not_enough_data" else "intervention_tracker.completed",
                    generated_at,
                    output_id,
                    Json({"response_label": response_label, "urgency_level": urgency_level}),
                ),
            )
            cur.execute(
                """
                INSERT INTO audit_logs (id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output)
                VALUES (%s, %s, 'agent', 'intervention_tracker', 'run_agent', 'intervention', %s, %s::jsonb, %s::jsonb)
                """,
                (
                    new_id("log"),
                    generated_at,
                    req.intervention_id,
                    Json(
                        {
                            "admission_id": req.admission_id,
                            "intervention_id": req.intervention_id,
                            "intervention_type": intervention_type,
                            "pre_window_minutes": pre_window_minutes,
                            "post_window_minutes": post_window_minutes,
                            "checkpoints": checkpoints,
                        }
                    ),
                    Json({
                        "response_label": response_label,
                        "status_event": output_event,
                        "urgency_level": urgency_level,
                        "retrieved_card_ids": [c["card_id"] for c in kctx["knowledge_background"]],
                    }),
                ),
            )

    return InterventionEvaluateResponse(
        admission_id=req.admission_id,
        patient_id=patient_id,
        bed_id=bed_id,
        intervention_id=req.intervention_id,
        intervention_type=intervention_type,
        intervention_time=intervention_time,
        assessment_window=AssessmentWindow(
            pre_window=f"{pre_window_minutes}min before intervention",
            post_window=f"{post_window_minutes}min after intervention",
        ),
        response_label=cast(Any, response_label),
        response_summary=response_summary,
        key_changes=key_changes,
        concern_flags=concern_flags,
        urgency_level=cast(Any, urgency_level),
        notify_agents=DEFAULT_NOTIFY_AGENTS,
        observation_window=observation_window,
        response_assessment=cast(Any, response_assessment),
        target_metrics=result["target_metrics"],
        before_after_comparison=result["before_after_comparison"],
        evidence=result["evidence"],
        escalation_hint=result["escalation_hint"],
        generated_at=generated_at,
        knowledge_background=kctx["knowledge_background"],
        response_explanation=kctx["response_explanation"],
        medication_safety_context=kctx["medication_safety_context"],
        forbidden_use_reminder=kctx["forbidden_use_reminder"],
        knowledge_used=kctx["knowledge_used"],
        llm_used=False,
        fallback_used=False,
        audit_log_id=None,
        human_review_required=True,
    )
