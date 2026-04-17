from __future__ import annotations

from fastapi import APIRouter, Depends
from psycopg import Connection

from app.db import get_db

from .schemas import RiskSentinelEvaluateRequest, RiskSentinelEvaluateResponse
from .service import evaluate_risk_sentinel

router = APIRouter(prefix="/agents/risk-sentinel", tags=["agents"])


@router.post("/evaluate", response_model=RiskSentinelEvaluateResponse)
def evaluate_risk_endpoint(
    request: RiskSentinelEvaluateRequest,
    conn: Connection = Depends(get_db),
) -> RiskSentinelEvaluateResponse:
    return evaluate_risk_sentinel(conn, request)