from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import datetime

class ApacheIIBreakdown(BaseModel):
    physiology: int
    age: int
    chronic_health: int
    total: int

class EvidenceItem(BaseModel):
    param: str
    worst_value: Optional[float] = None
    score: int
    reason: str

class RiskAssessmentRequest(BaseModel):
    admission_id: str
    temporal_state: Dict # 来自 Patient Memory 的 TemporalStateSummary dict
    age: int
    chronic_health_status: Optional[str] = None # 如 "severe_organ_insufficiency"
    is_elective_surgery: bool = False
    window_hours: int = 24

class RiskAssessment(BaseModel):
    admission_id: str
    timestamp: datetime
    risk_type: str = "apache_ii_comprehensive"
    confidence: float
    severity: str = Field(default="low", pattern="^(low|warning|critical)$")
    evidence: List[EvidenceItem]
    time_window: str
    recommended_action: Optional[str] = None
    apache_ii_breakdown: ApacheIIBreakdown
    intervention_context_impact: Optional[str] = None
    urgency_adjusted: bool = False
    trend_direction: str