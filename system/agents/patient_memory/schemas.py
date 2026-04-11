from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from datetime import datetime

# 对齐 vital_sign_events 表结构
class VitalSignEvent(BaseModel):
    id: Optional[str] = None
    admission_id: str
    timestamp: datetime
    heart_rate: Optional[float] = None
    mean_arterial_pressure: Optional[float] = None
    systolic_bp: Optional[float] = None
    diastolic_bp: Optional[float] = None
    respiratory_rate: Optional[float] = None
    temperature: Optional[float] = None
    spo2: Optional[float] = None
    fio2: Optional[float] = None
    pao2: Optional[float] = None
    aado2: Optional[float] = None
    ph: Optional[float] = None
    gcs: Optional[float] = None

# 对齐 lab_events 表结构
class LabEvent(BaseModel):
    id: Optional[str] = None
    admission_id: str
    timestamp: datetime
    lab_type: str
    value: float
    unit: str
    abnormal_flag: Optional[str] = None

# 对齐 intervention_events 表结构
class InterventionEvent(BaseModel):
    id: Optional[str] = None
    admission_id: str
    timestamp: datetime
    intervention_type: str
    description: Optional[str] = None
    dosage: Optional[float] = None
    unit: Optional[str] = None
    response_hint: Optional[str] = None  # 来自上层 tracker 评估

class MemoryRequest(BaseModel):
    admission_id: str
    window_hours: int = Field(default=6, ge=1, le=72)
    vital_sign_events: List[VitalSignEvent]
    lab_events: List[LabEvent] = []
    intervention_events: List[InterventionEvent] = []

class TemporalStateSummary(BaseModel):
    admission_id: str
    window_hours: int
    current_vitals: Dict[str, Optional[float]]
    trend_vectors: Dict[str, str]
    volatility_index: Dict[str, float]
    latest_interventions: List[InterventionEvent]
    data_completeness_ratio: float
    snapshot_generated_at: datetime