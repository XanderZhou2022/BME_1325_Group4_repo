from __future__ import annotations

from fastapi import APIRouter, Depends
from psycopg import Connection

from app.db import get_db

from .schemas import BedsideAnalyzeRequest, BedsideAnalyzeResponse
from .service import analyze_bedside


router = APIRouter(prefix="/agents/bedside-monitor", tags=["agents"])


@router.post("/analyze", response_model=BedsideAnalyzeResponse)
def analyze(request: BedsideAnalyzeRequest, conn: Connection = Depends(get_db)) -> BedsideAnalyzeResponse:
    return analyze_bedside(conn, request)

