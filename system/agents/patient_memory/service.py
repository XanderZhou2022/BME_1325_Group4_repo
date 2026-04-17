from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.ids import new_id

from .schemas import (
    MemoryEvaluateRequest,
    MemoryEvaluateResponse,
    MemoryRequest,
    TemporalStateSummary,
    VitalSignEvent,
    LabEvent,
    InterventionEvent,
)
from .memory_manager import calculate_trend_for_metric, calculate_volatility, extract_window_data


def process_memory(request: MemoryRequest) -> TemporalStateSummary:
    current_time = datetime.now(timezone.utc)
    vital_metrics = ["heart_rate", "mean_arterial_pressure", "respiratory_rate", "temperature", "spo2"]
    current_vitals = {}
    trend_vectors = {}
    volatility_index = {}
    all_completeness = []

    for metric in vital_metrics:
        def extractor(e):
            return getattr(e, metric)

        def time_ext(e):
            return e.timestamp

        values, _times, comp = extract_window_data(
            request.vital_sign_events, current_time, request.window_hours, extractor, time_ext
        )
        all_completeness.append(comp)

        if values:
            current_vitals[metric] = values[-1]
            trend_vectors[metric] = calculate_trend_for_metric(metric, values)
            volatility_index[metric] = calculate_volatility(values)
        else:
            current_vitals[metric] = None

    interventions_sorted = sorted(request.intervention_events, key=lambda x: x.timestamp, reverse=True)
    latest_interventions = interventions_sorted[:3]
    avg_completeness = sum(all_completeness) / len(all_completeness) if all_completeness else 0.0

    return TemporalStateSummary(
        admission_id=request.admission_id,
        window_hours=request.window_hours,
        current_vitals=current_vitals,
        trend_vectors=trend_vectors,
        volatility_index=volatility_index,
        latest_interventions=latest_interventions,
        data_completeness_ratio=avg_completeness,
        snapshot_generated_at=current_time,
    )


def evaluate_memory(conn: Connection, req: MemoryEvaluateRequest) -> MemoryEvaluateResponse:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("SELECT patient_id, bed_id FROM admissions WHERE admission_id = %s", (req.admission_id,))
        admission = cur.fetchone()
        if not admission:
            raise HTTPException(status_code=404, detail="Admission not found")

        cur.execute(
            """
            SELECT id, admission_id, timestamp, heart_rate, mean_arterial_pressure, systolic_bp, diastolic_bp,
                   respiratory_rate, temperature, spo2, fio2, pao2, aado2, ph, gcs
            FROM vital_sign_events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT 500
            """,
            (req.admission_id,),
        )
        vitals_rows = cur.fetchall()

        cur.execute(
            """
            SELECT id, admission_id, timestamp, lab_type, value, unit, abnormal_flag
            FROM lab_events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT 300
            """,
            (req.admission_id,),
        )
        lab_rows = cur.fetchall()

        cur.execute(
            """
            SELECT id, admission_id, timestamp, intervention_type, description, dosage, unit
            FROM intervention_events
            WHERE admission_id = %s
            ORDER BY timestamp DESC
            LIMIT 200
            """,
            (req.admission_id,),
        )
        intervention_rows = cur.fetchall()

    mem_req = MemoryRequest(
        admission_id=req.admission_id,
        window_hours=req.window_hours,
        vital_sign_events=[VitalSignEvent(**r) for r in vitals_rows],
        lab_events=[LabEvent(**r) for r in lab_rows],
        intervention_events=[InterventionEvent(**r) for r in intervention_rows],
    )
    summary = process_memory(mem_req)
    now = datetime.now(timezone.utc)

    payload = {
        "window_hours": summary.window_hours,
        "current_vitals": summary.current_vitals,
        "trend_vectors": summary.trend_vectors,
        "volatility_index": summary.volatility_index,
        "latest_interventions": [i.model_dump(mode="json") for i in summary.latest_interventions],
        "data_completeness_ratio": summary.data_completeness_ratio,
        "snapshot_generated_at": summary.snapshot_generated_at.isoformat(),
    }

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_registry (agent_name, input_event_types, output_event_type, schema_version, enabled)
                VALUES ('patient_memory', '["vital_sign","lab","intervention"]'::jsonb, 'patient_memory_ready', 'v1', TRUE)
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
                ) VALUES (%s, %s, %s, %s, 'patient_memory', 'v1', 'patient_memory_ready', %s, %s::jsonb)
                """,
                (output_id, req.admission_id, admission["patient_id"], admission["bed_id"], now, Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'patient_memory', 'patient_memory_ready', 'v1', %s, %s, %s::jsonb)
                """,
                (event_id, req.admission_id, admission["patient_id"], admission["bed_id"], now, output_id, Json(payload)),
            )

    return MemoryEvaluateResponse(
        patient_id=admission["patient_id"],
        bed_id=admission["bed_id"],
        admission_id=req.admission_id,
        window_hours=summary.window_hours,
        current_vitals=summary.current_vitals,
        trend_vectors=summary.trend_vectors,
        volatility_index=summary.volatility_index,
        latest_interventions=summary.latest_interventions,
        data_completeness_ratio=summary.data_completeness_ratio,
        snapshot_generated_at=summary.snapshot_generated_at,
        generated_at=now,
    )
