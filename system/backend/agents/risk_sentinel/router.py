from fastapi import APIRouter
from .schemas import RiskAssessmentRequest, RiskAssessment
from .service import calculate_risk

router = APIRouter(prefix="/agents/risk-sentinel", tags=["Risk Sentinel"])

@router.post("/evaluate", response_model=RiskAssessment)
def evaluate_risk_endpoint(request: RiskAssessmentRequest):
    """
    Endpoint to evaluate patient risk using APACHE II and intervention context.
    """
    return calculate_risk(request)