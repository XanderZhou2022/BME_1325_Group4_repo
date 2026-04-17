from __future__ import annotations

from fastapi import APIRouter, Depends
from psycopg import Connection

from app.db import get_db

from .schemas import WardCoordinatorEvaluateRequest, WardCoordinatorEvaluateResponse
from .service import evaluate_ward

router = APIRouter(prefix="/agents/ward-coordinator", tags=["agents"])


@router.post("/evaluate", response_model=WardCoordinatorEvaluateResponse)
def evaluate(request: WardCoordinatorEvaluateRequest, conn: Connection = Depends(get_db)) -> WardCoordinatorEvaluateResponse:
    return evaluate_ward(conn, request)
