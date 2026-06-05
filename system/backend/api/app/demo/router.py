from __future__ import annotations

import json
from queue import Queue
from threading import Thread
from typing import Any

import psycopg
from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse
from psycopg import Connection

from app.config import get_settings
from app.db import get_db

from .progress import progress_scope
from .schemas import DemoHospitalState, DemoNextResponse, DemoTimelineResponse
from .service import (
    add_random_demo_patient,
    discharge_demo_patient,
    get_demo_state,
    list_timeline,
    next_demo_step,
    reset_demo_auto,
    transfer_demo_patient_to_inpatient,
)

router = APIRouter(prefix="/demo/auto", tags=["demo-auto"])


@router.post("/reset", response_model=DemoHospitalState)
def reset(conn: Connection = Depends(get_db)) -> DemoHospitalState:
    return reset_demo_auto(conn)


@router.post("/next", response_model=DemoNextResponse)
def next_step(conn: Connection = Depends(get_db)) -> DemoNextResponse:
    return next_demo_step(conn)


@router.post("/admit-random")
def admit_random(conn: Connection = Depends(get_db)) -> dict[str, Any]:
    return add_random_demo_patient(conn)


@router.post("/admissions/{admission_id}/discharge")
def discharge_admission(admission_id: str, conn: Connection = Depends(get_db)) -> dict[str, Any]:
    return discharge_demo_patient(conn, admission_id)


@router.post("/admissions/{admission_id}/transfer-out")
def transfer_admission_to_inpatient(
    admission_id: str,
    conn: Connection = Depends(get_db),
    body: dict[str, Any] = Body(default={"force": True}),
) -> dict[str, Any]:
    force = bool(body.get("force", True))
    return transfer_demo_patient_to_inpatient(conn, admission_id, force=force)


@router.post("/next/stream")
def next_step_stream() -> StreamingResponse:
    """NDJSON stream: progress events, then `{type: result, data: ...}` or `{type: error}`."""

    q: Queue[dict[str, Any] | None] = Queue()

    def enqueue(ev: dict[str, Any]) -> None:
        q.put(ev)

    def worker() -> None:
        try:
            settings = get_settings()
            with progress_scope(enqueue):
                with psycopg.connect(settings.pg_dsn) as conn:
                    resp = next_demo_step(conn)
            q.put({"type": "result", "data": resp.model_dump(mode="json")})
        except Exception as exc:
            q.put({"type": "error", "message": str(exc)})
        finally:
            q.put(None)

    Thread(target=worker, daemon=True).start()

    def generate():
        while True:
            item = q.get()
            if item is None:
                break
            yield json.dumps(item, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.get("/state", response_model=DemoHospitalState)
def state(conn: Connection = Depends(get_db)) -> DemoHospitalState:
    return get_demo_state(conn)


@router.get("/timeline", response_model=DemoTimelineResponse)
def timeline(limit: int = 100, conn: Connection = Depends(get_db)) -> DemoTimelineResponse:
    items = list_timeline(conn, limit=limit)
    return DemoTimelineResponse(items=items, total=len(items))
