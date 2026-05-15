from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal, Any
from datetime import datetime

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

class LabEvent(BaseModel):
    id: Optional[str] = None
    admission_id: str
    timestamp: datetime
    lab_type: str
    value: float
    unit: str
    abnormal_flag: Optional[str] = None

class InterventionEvent(BaseModel):
    id: Optional[str] = None
    admission_id: str
    timestamp: datetime
    intervention_type: str
    description: Optional[str] = None
    dosage: Optional[float] = None
    unit: Optional[str] = None
    response_hint: Optional[str] = None

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

class MemoryEvaluateRequest(BaseModel):
    admission_id: str
    window_hours: int = Field(default=24, ge=1, le=72)
    short_window_hours: int = Field(default=6, ge=1, le=24)
    mid_window_hours: int = Field(default=24, ge=6, le=72)


class ShortTermMemory(BaseModel):
    time_window: str
    key_events: List[str] = []
    current_unstable_features: List[str] = []


class MidTermMemory(BaseModel):
    time_window: str
    major_changes: List[str] = []
    unresolved_problems: List[str] = []


class LongTermMemory(BaseModel):
    icu_course_summary: str
    baseline_context: List[str] = []
    known_response_patterns: List[str] = []

class MemoryEvaluateResponse(BaseModel):
    schema_version: str = "patient_memory.v1.1"
    agent: str = "patient_memory"
    status: Literal["ok", "degraded"] = "ok"
    patient_id: str
    bed_id: str
    admission_id: str
    window_hours: int
    short_term_summary: str
    mid_term_summary: str
    long_term_summary: str
    active_problems: List[str] = []
    unresolved_issues: List[str] = []
    short_term_memory: ShortTermMemory
    mid_term_memory: MidTermMemory
    long_term_memory: LongTermMemory
    current_vitals: Dict[str, Optional[float]]
    trend_vectors: Dict[str, str]
    volatility_index: Dict[str, float]
    latest_interventions: List[InterventionEvent]
    data_completeness_ratio: float
    source_event_ids: List[str] = []
    key_events: List[str] = []
    response_patterns: List[str] = []
    memory_context_for_risk: Dict[str, Any] = {}
    round_memory_for_summary: Dict[str, Any] = {}
    snapshot_generated_at: datetime
    generated_at: datetime
    short_term_narrative: str = ""
    intervention_response_memory: List[str] = []
    communication_relevant_context: List[str] = []
    knowledge_context: List[Dict[str, Any]] = []
    forbidden_use_reminder: List[str] = []
    knowledge_used: bool = False
    llm_used: bool = False
    fallback_used: bool = False
    audit_log_id: str | None = None
    human_review_required: bool = True
