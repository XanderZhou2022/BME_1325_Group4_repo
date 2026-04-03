from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

from fastapi import HTTPException
from psycopg import Connection
from psycopg.rows import dict_row

from .rules import run_bedside_monitor

from .schemas import BedsideAnalyzeRequest, BedsideAnalyzeResponse, VitalPoint

from agents.shared_patient_state_board.schemas import SharedBoardEntry
from agents.shared_patient_state_board.service import update_shared_board_snapshot


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
    max_ts = row[0] if row else None
    if max_ts is None:
        raise HTTPException(status_code=404, detail="No vital_sign_events found for admission_id")
    return cast(datetime, max_ts)


def analyze_bedside(conn: Connection, req: BedsideAnalyzeRequest) -> BedsideAnalyzeResponse:
    patient_bed: dict[str, str] = {}
    with conn.cursor() as cur:
        cur.row_factory = dict_row
        cur.execute(
            "SELECT patient_id, bed_id FROM admissions WHERE admission_id = %s",
            (req.admission_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Admission not found")
        patient_bed = {"patient_id": row["patient_id"], "bed_id": row["bed_id"]}

    analysis_end = _analysis_end_from_request(conn, admission_id=req.admission_id, request_end=req.analysis_end)
    minutes = ANALYSIS_WINDOW_TO_MINUTES[req.analysis_window]
    start_ts = analysis_end - timedelta(minutes=minutes)

    vitals: list[VitalPoint] = []
    with conn.cursor() as cur:
        cur.row_factory = dict_row
        cur.execute(
            """
            SELECT timestamp,
                   heart_rate,
                   mean_arterial_pressure,
                   respiratory_rate,
                   temperature,
                   spo2
            FROM vital_sign_events
            WHERE admission_id = %s
              AND timestamp >= %s
              AND timestamp <= %s
            ORDER BY timestamp ASC
            """,
            (req.admission_id, start_ts, analysis_end),
        )
        rows = cur.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No vital_sign_events found in requested analysis window")

    for r in rows:
        vitals.append(
            VitalPoint(
                timestamp=r["timestamp"],
                heart_rate=r["heart_rate"],
                mean_arterial_pressure=float(r["mean_arterial_pressure"]) if r["mean_arterial_pressure"] is not None else None,
                respiratory_rate=float(r["respiratory_rate"]) if r["respiratory_rate"] is not None else None,
                temperature=float(r["temperature"]) if r["temperature"] is not None else None,
                spo2=float(r["spo2"]) if r["spo2"] is not None else None,
            )
        )

    result = run_bedside_monitor(
        vitals=vitals,
        urine_output_points=req.urine_output_points,
        analysis_end=analysis_end,
    )

    # Persist unified shared patient state board entry (for downstream Risk Sentinel).
    shared_entry = SharedBoardEntry(
        patient_id=patient_bed["patient_id"],
        bed_id=patient_bed["bed_id"],
        timestamp=datetime.now(timezone.utc),
        source_agent="bedside_monitor",
        summary=result["current_status_summary"],
        evidence=result["evidence"],
        urgency=result["urgency_level"],
        structured_payload={
            "analysis_window": req.analysis_window,
            "abnormal_flags": result["abnormal_flags"],
            "trend_labels": result["trend_labels"],
        },
    )
    update_shared_board_snapshot(conn, admission_id=req.admission_id, entry=shared_entry)

    return BedsideAnalyzeResponse(
        patient_id=patient_bed["patient_id"],
        bed_id=patient_bed["bed_id"],
        analysis_window=req.analysis_window,
        current_status_summary=result["current_status_summary"],
        abnormal_flags=result["abnormal_flags"],
        trend_labels=result["trend_labels"],
        evidence=result["evidence"],
        urgency_level=result["urgency_level"],
        generated_at=datetime.now(timezone.utc),
    )

