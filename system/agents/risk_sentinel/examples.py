from .schemas import RiskAssessmentRequest

# Mock temporal state from Patient Memory Agent
SAMPLE_TEMPORAL_STATE = {
    "admission_id": "adm1",
    "window_hours": 6,
    "current_vitals": {
        "heart_rate": 115,
        "mean_arterial_pressure": 62,
        "respiratory_rate": 24,
        "temperature": 39.2,
        "spo2": 89,
        "ph": 7.28
    },
    "latest_interventions": [
        {
            "id": "i1",
            "intervention_type": "fluid",
            "timestamp": "2023-10-27T10:00:00Z",
            "response_hint": "partially_responsive"
        }
    ],
    "data_completeness_ratio": 0.9
}

SAMPLE_REQUEST = RiskAssessmentRequest(
    admission_id="adm1",
    temporal_state=SAMPLE_TEMPORAL_STATE,
    age=68,
    chronic_health_status="severe_organ_insufficiency",
    is_elective_surgery=False,
    window_hours=24
)