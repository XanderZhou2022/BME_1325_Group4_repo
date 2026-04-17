from __future__ import annotations

from fastapi import APIRouter, Depends
from psycopg import Connection

from app.db import get_db

from .schemas import MemoryRequest, MemoryEvaluateRequest, MemoryEvaluateResponse, TemporalStateSummary
from .service import evaluate_memory, process_memory

router = APIRouter(prefix="/agents/patient-memory", tags=["agents"])


@router.post("/state", response_model=TemporalStateSummary)
def get_patient_state(request: MemoryRequest) -> TemporalStateSummary:
    return process_memory(request)


@router.post("/evaluate", response_model=MemoryEvaluateResponse)
def evaluate(request: MemoryEvaluateRequest, conn: Connection = Depends(get_db)) -> MemoryEvaluateResponse:
    return evaluate_memory(conn, request)
