from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.ids import new_id
from .rules import run_intervention_tracker
from .schemas import InterventionEvaluateRequest, InterventionEvaluateResponse, InterventionType, VitalPoint


DEFAULT_PRE_WINDOW_MINUTES = 60
DEFAULT_POST_WINDOW_MINUTES = 60


def evaluate_intervention_tracker(conn: Connection, req: InterventionEvaluateRequest) -> InterventionEvaluateResponse:
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

    pre_window_minutes = req.pre_window_minutes or DEFAULT_PRE_WINDOW_MINUTES
    if req.post_window_minutes is not None:
        post_window_minutes = req.post_window_minutes
    elif req.expected_observation_window_minutes is not None:
        post_window_minutes = req.expected_observation_window_minutes
    else:
        post_window_minutes = DEFAULT_POST_WINDOW_MINUTES

    pre_start = intervention_time - timedelta(minutes=pre_window_minutes)
    post_end = intervention_time + timedelta(minutes=post_window_minutes)

    # --- vitals slice ---
    vitals: list[VitalPoint] = []
    with conn.cursor() as cur:
        cur.row_factory = dict_row
        cur.execute(
            """
            SELECT timestamp,
                   mean_arterial_pressure,
                   spo2,
                   respiratory_rate
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
                mean_arterial_pressure=float(r["mean_arterial_pressure"]) if r["mean_arterial_pressure"] is not None else None,
                spo2=float(r["spo2"]) if r["spo2"] is not None else None,
                respiratory_rate=float(r["respiratory_rate"]) if r["respiratory_rate"] is not None else None,
            )
        )

    pre_vitals = [v for v in vitals if v.timestamp <= intervention_time]
    post_vitals = [v for v in vitals if v.timestamp > intervention_time]

    observation_window = f"pre {pre_window_minutes}m / post {post_window_minutes}m"
    result = run_intervention_tracker(
        intervention_type=intervention_type,
        intervention_time=intervention_time,
        pre_vitals=pre_vitals,
        post_vitals=post_vitals,
        observation_window=observation_window,
    )
    generated_at = datetime.now(timezone.utc)
    payload = {
        "intervention_type": intervention_type,
        "intervention_time": intervention_time.isoformat(),
        "observation_window": observation_window,
        "response_assessment": result["response_assessment"],
        "target_metrics": result["target_metrics"],
        "before_after_comparison": result["before_after_comparison"],
        "evidence": result["evidence"],
        "escalation_hint": result["escalation_hint"],
        "generated_at": generated_at.isoformat(),
    }

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_registry (agent_name, input_event_types, output_event_type, schema_version, enabled)
                VALUES ('intervention_tracker', '["intervention"]'::jsonb, 'intervention_evaluation_ready', 'v1', TRUE)
                ON CONFLICT (agent_name) DO UPDATE SET enabled = TRUE, updated_at = NOW()
                """
            )
            output_id = new_id("out")
            event_id = new_id("aevt")
            cur.execute(
                """
                INSERT INTO agent_outputs (
                    output_id, admission_id, patient_id, bed_id, agent_name,
                    schema_version, output_type, generated_at, payload
                ) VALUES (%s, %s, %s, %s, 'intervention_tracker', 'v1', 'intervention_evaluation_ready', %s, %s::jsonb)
                """,
                (output_id, req.admission_id, patient_id, bed_id, generated_at, Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'intervention_tracker', 'intervention_evaluation_ready', 'v1', %s, %s, %s::jsonb)
                """,
                (event_id, req.admission_id, patient_id, bed_id, generated_at, output_id, Json(payload)),
            )

    return InterventionEvaluateResponse(
        patient_id=patient_id,
        bed_id=bed_id,
        intervention_type=intervention_type,
        intervention_time=intervention_time,
        observation_window=observation_window,
        response_assessment=result["response_assessment"],
        target_metrics=result["target_metrics"],
        before_after_comparison=result["before_after_comparison"],
        evidence=result["evidence"],
        escalation_hint=result["escalation_hint"],
        generated_at=generated_at,
    )

