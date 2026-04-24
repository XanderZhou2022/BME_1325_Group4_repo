from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.services.ids import new_id
from app.services.state_merge import infer_care_phase_from_vitals, merge_vitals_into_current
from .rules import run_bedside_rules

from .schemas import AbnormalFlag, BedsideAnalyzeRequest, BedsideAnalyzeResponse, TimeWindow, TrendLabel, VitalPoint


ANALYSIS_WINDOW_TO_MINUTES: dict[str, int] = {
    "last_1h": 60,
    "last_4h": 240,
    "last_6h": 360,
}


def _analysis_end_from_request(
    conn: Connection,
    *,
    admission_id: str,
    request_end: datetime | None,
) -> datetime:
    if request_end is not None:
        return request_end if request_end.tzinfo is not None else request_end.replace(tzinfo=timezone.utc)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(timestamp) AS max_ts FROM vital_sign_events WHERE admission_id = %s",
            (admission_id,),
        )
        row = cur.fetchone()
    if not row:
        max_ts = None
    elif isinstance(row, dict):
        max_ts = row.get("max_ts")
    else:
        max_ts = row[0]
    if max_ts is None:
        return datetime.now(timezone.utc)
    dt = cast(datetime, max_ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _get_admission_context(conn: Connection, admission_id: str) -> dict[str, str]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT a.patient_id, a.bed_id
            FROM admissions a
            JOIN patients p ON p.patient_id = a.patient_id
            JOIN beds b ON b.bed_id = a.bed_id
            WHERE a.admission_id = %s
            """,
            (admission_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Admission not found")
    return {"patient_id": row["patient_id"], "bed_id": row["bed_id"]}


def _vitals_from_db(conn: Connection, admission_id: str, start_ts: datetime, end_ts: datetime) -> list[VitalPoint]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT timestamp,
                   heart_rate,
                   mean_arterial_pressure,
                   respiratory_rate,
                   temperature,
                   spo2,
                   gcs
            FROM vital_sign_events
            WHERE admission_id = %s
              AND timestamp >= %s
              AND timestamp <= %s
            ORDER BY timestamp ASC
            """,
            (admission_id, start_ts, end_ts),
        )
        rows = cur.fetchall()
    return [
        VitalPoint(
            timestamp=r["timestamp"],
            heart_rate=r["heart_rate"],
            mean_arterial_pressure=float(r["mean_arterial_pressure"]) if r["mean_arterial_pressure"] is not None else None,
            respiratory_rate=float(r["respiratory_rate"]) if r["respiratory_rate"] is not None else None,
            temperature=float(r["temperature"]) if r["temperature"] is not None else None,
            spo2=float(r["spo2"]) if r["spo2"] is not None else None,
            gcs=r["gcs"],
        )
        for r in rows
    ]


def _safe_payload(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _safe_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_payload(v) for v in value]
    return value


def run_bedside_monitor(
    conn: Connection,
    admission_id: str,
    window_minutes: int = 90,
    trend_hours: int = 6,
    analysis_end: datetime | None = None,
    urine_output_points: list | None = None,
) -> BedsideAnalyzeResponse:
    context = _get_admission_context(conn, admission_id)
    patient_id = context["patient_id"]
    bed_id = context["bed_id"]
    run_started_at = datetime.now(timezone.utc)
    end_ts = analysis_end or _analysis_end_from_request(conn, admission_id=admission_id, request_end=None)
    if end_ts.tzinfo is None:
        end_ts = end_ts.replace(tzinfo=timezone.utc)
    data_start = end_ts - timedelta(hours=trend_hours)
    current_start = end_ts - timedelta(minutes=window_minutes)
    vitals = _vitals_from_db(conn, admission_id, data_start, end_ts)
    rule_out = run_bedside_rules(
        vitals=vitals,
        urine_output_points=urine_output_points,
        analysis_end=end_ts,
        window_minutes=window_minutes,
        trend_hours=trend_hours,
    )
    now = datetime.now(timezone.utc)
    response = BedsideAnalyzeResponse(
        status=cast(str, rule_out["status"]),
        admission_id=admission_id,
        patient_id=patient_id,
        bed_id=bed_id,
        time_window=TimeWindow(
            start=current_start,
            end=end_ts,
            window_minutes=window_minutes,
            trend_hours=trend_hours,
        ),
        current_status_summary=cast(str, rule_out["current_status_summary"]),
        abnormal_flags=[AbnormalFlag(**item) for item in cast(list[dict[str, Any]], rule_out["abnormal_flags"])],
        trend_labels=[TrendLabel(**item) for item in cast(list[dict[str, Any]], rule_out["trend_labels"])],
        evidence=cast(dict[str, Any], rule_out["evidence"]),
        urgency_level=cast(str, rule_out["urgency_level"]),
        next_action_hint=cast(str, rule_out["next_action_hint"]),
        generated_at=now,
    )
    payload = _safe_payload(response.model_dump(mode="json"))
    latest_vitals = cast(dict[str, Any], payload["evidence"].get("latest_vitals") or {})

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_registry (agent_name, input_event_types, output_event_type, schema_version, enabled)
                VALUES ('bedside_monitor', '["vital_sign"]'::jsonb, 'bedside_analysis_ready', 'v1', TRUE)
                ON CONFLICT (agent_name) DO UPDATE SET enabled = TRUE, updated_at = NOW()
                """
            )
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'bedside_monitor', 'bedside_monitor.started', 'v1', %s, NULL, %s::jsonb)
                """,
                (new_id("aevt"), admission_id, patient_id, bed_id, run_started_at, Json({"window_minutes": window_minutes, "trend_hours": trend_hours})),
            )
            output_id = new_id("out")
            cur.execute(
                """
                INSERT INTO agent_outputs (
                    output_id, admission_id, patient_id, bed_id, agent_name,
                    schema_version, output_type, generated_at, payload
                ) VALUES (%s, %s, %s, %s, 'bedside_monitor', 'v1', 'bedside_analysis_ready', %s, %s::jsonb)
                """,
                (output_id, admission_id, patient_id, bed_id, now, Json(payload)),
            )
            cur.execute(
                """
                INSERT INTO agent_events (
                    event_id, admission_id, patient_id, bed_id, producer_agent,
                    event_type, schema_version, produced_at, output_id, payload
                ) VALUES (%s, %s, %s, %s, 'bedside_monitor', 'bedside_monitor.completed', 'v1', %s, %s, %s::jsonb)
                """,
                (new_id("aevt"), admission_id, patient_id, bed_id, now, output_id, Json({"status": response.status, "urgency_level": response.urgency_level})),
            )
            if response.urgency_level in ("warning", "critical"):
                cur.execute(
                    """
                    INSERT INTO agent_events (
                        event_id, admission_id, patient_id, bed_id, producer_agent,
                        event_type, schema_version, produced_at, output_id, payload
                    ) VALUES (%s, %s, %s, %s, 'bedside_monitor', %s, 'v1', %s, %s, %s::jsonb)
                    """,
                    (
                        new_id("aevt"),
                        admission_id,
                        patient_id,
                        bed_id,
                        f"bedside_monitor.{response.urgency_level}_detected",
                        now,
                        output_id,
                        Json({"abnormal_flags": [f.model_dump(mode="json") for f in response.abnormal_flags]}),
                    ),
                )
            if latest_vitals:
                cur.execute(
                    """
                    INSERT INTO patient_state_current (
                        admission_id, patient_id, bed_id, updated_at, current_vitals, active_problems, active_risks, latest_interventions, care_phase
                    ) VALUES (%s, %s, %s, NOW(), %s::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, %s)
                    ON CONFLICT (admission_id) DO UPDATE SET
                        updated_at = NOW(),
                        current_vitals = %s::jsonb,
                        care_phase = %s
                    """,
                    (
                        admission_id,
                        patient_id,
                        bed_id,
                        Json(latest_vitals),
                        infer_care_phase_from_vitals(latest_vitals),
                        Json(merge_vitals_into_current({}, latest_vitals)),
                        infer_care_phase_from_vitals(latest_vitals),
                    ),
                )
            cur.execute(
                """
                INSERT INTO audit_logs (id, timestamp, actor, actor_id, action_type, target_type, target_id, input, output)
                VALUES (%s, %s, 'agent', 'bedside_monitor', 'run_agent', 'admission', %s, %s::jsonb, %s::jsonb)
                """,
                (
                    new_id("log"),
                    now,
                    admission_id,
                    Json({"admission_id": admission_id, "window_minutes": window_minutes, "trend_hours": trend_hours, "start": current_start.isoformat(), "end": end_ts.isoformat()}),
                    Json({"status": response.status, "urgency_level": response.urgency_level, "abnormal_count": len(response.abnormal_flags), "output_id": output_id}),
                ),
            )
    return response


def analyze_bedside(conn: Connection, req: BedsideAnalyzeRequest) -> BedsideAnalyzeResponse:
    minutes = ANALYSIS_WINDOW_TO_MINUTES.get(req.analysis_window, 90)
    return run_bedside_monitor(
        conn,
        admission_id=req.admission_id,
        window_minutes=minutes,
        trend_hours=6,
        analysis_end=req.analysis_end,
        urine_output_points=req.urine_output_points,
    )

