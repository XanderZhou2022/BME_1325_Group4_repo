from datetime import datetime, timedelta
from .schemas import MemoryRequest, VitalSignEvent, InterventionEvent, LabEvent

now = datetime.utcnow()

SAMPLE_REQUEST = MemoryRequest(
    admission_id="adm1",
    window_hours=6,
    vital_sign_events=[
        VitalSignEvent(
            id="v1",
            admission_id="adm1",
            timestamp=now - timedelta(minutes=30),
            heart_rate=115,
            mean_arterial_pressure=62,
            respiratory_rate=22,
            temperature=38.8,
            spo2=91
        ),
        VitalSignEvent(
            id="v2",
            admission_id="adm1",
            timestamp=now - timedelta(minutes=90),
            heart_rate=105,
            mean_arterial_pressure=68,
            respiratory_rate=20,
            temperature=38.5,
            spo2=94
        )
    ],
    lab_events=[
        LabEvent(
            id="l1",
            admission_id="adm1",
            timestamp=now - timedelta(hours=4),
            lab_type="lactate",
            value=2.8,
            unit="mmol/L"
        )
    ],
    intervention_events=[
        InterventionEvent(
            id="i1",
            admission_id="adm1",
            timestamp=now - timedelta(hours=1),
            intervention_type="fluid",
            description="500ml NS",
            dosage=500,
            unit="ml"
        )
    ]
)