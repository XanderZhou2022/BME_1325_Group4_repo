from fastapi import APIRouter
from .schemas import MemoryRequest, TemporalStateSummary
from .service import process_memory

router = APIRouter(prefix="/agents/patient-memory", tags=["Patient Memory"])

@router.post("/state", response_model=TemporalStateSummary)
def get_patient_state(request: MemoryRequest):
    return process_memory(request)