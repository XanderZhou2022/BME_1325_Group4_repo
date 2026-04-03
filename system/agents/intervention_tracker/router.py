from __future__ import annotations

from fastapi import APIRouter, Depends
from psycopg import Connection

from app.db import get_db

from .schemas import InterventionEvaluateRequest, InterventionEvaluateResponse
from .service import evaluate_intervention_tracker


router = APIRouter(prefix="/agents/intervention-tracker", tags=["agents"])


@router.post("/evaluate", response_model=InterventionEvaluateResponse)
def evaluate(request: InterventionEvaluateRequest, conn: Connection = Depends(get_db)) -> InterventionEvaluateResponse:
    return evaluate_intervention_tracker(conn, request)

