from __future__ import annotations

from fastapi import APIRouter, Depends
from psycopg import Connection

from app.db import get_db

from .schemas import DemoHospitalState, DemoNextResponse, DemoTimelineResponse
from .service import get_demo_state, list_timeline, next_demo_step, reset_demo_auto

router = APIRouter(prefix="/demo/auto", tags=["demo-auto"])


@router.post("/reset", response_model=DemoHospitalState)
def reset(conn: Connection = Depends(get_db)) -> DemoHospitalState:
    return reset_demo_auto(conn)


@router.post("/next", response_model=DemoNextResponse)
def next_step(conn: Connection = Depends(get_db)) -> DemoNextResponse:
    return next_demo_step(conn)


@router.get("/state", response_model=DemoHospitalState)
def state(conn: Connection = Depends(get_db)) -> DemoHospitalState:
    return get_demo_state(conn)


@router.get("/timeline", response_model=DemoTimelineResponse)
def timeline(limit: int = 100, conn: Connection = Depends(get_db)) -> DemoTimelineResponse:
    items = list_timeline(conn, limit=limit)
    return DemoTimelineResponse(items=items, total=len(items))
