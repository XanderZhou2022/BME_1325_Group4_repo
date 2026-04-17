from __future__ import annotations

from fastapi import APIRouter, Depends
from psycopg import Connection

from app.db import get_db

from .schemas import ClinicalSummaryRequest, ClinicalSummaryResponse
from .service import evaluate_clinical_summary, generate_summary

router = APIRouter(prefix="/agents/clinical-summary", tags=["agents"])


@router.post("/generate", response_model=ClinicalSummaryResponse)
def generate(request: ClinicalSummaryRequest) -> ClinicalSummaryResponse:
    return generate_summary(request)


@router.post("/evaluate/{admission_id}", response_model=ClinicalSummaryResponse)
def evaluate(admission_id: str, conn: Connection = Depends(get_db)) -> ClinicalSummaryResponse:
    return evaluate_clinical_summary(conn, admission_id)
