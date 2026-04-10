from __future__ import annotations

from fastapi import APIRouter

from .schemas import ClinicalSummaryRequest, ClinicalSummaryResponse
from .service import generate_summary

router = APIRouter(prefix="/agents/clinical-summary", tags=["agents"])


@router.post("/generate", response_model=ClinicalSummaryResponse)
def generate(request: ClinicalSummaryRequest) -> ClinicalSummaryResponse:
    """
    Generate a clinical summary for a single patient based on the outputs
    of Bedside Monitor, Intervention Tracker, Risk Sentinel, and Patient Memory.
    """
    return generate_summary(request)