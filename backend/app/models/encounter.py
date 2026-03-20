from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.clinical_state import ClinicalState
from app.models.message import Message, Role, utc_now_iso
from app.models.patient_memory import PatientMemory


Stage = Literal["triage", "consultation", "pharmacy", "completed"]
Room = Literal["lobby", "triage_room", "doctor_room", "pharmacy_room"]

Status = Literal["in_progress", "completed"]


class EncounterState(BaseModel):
    id: str
    status: Status
    stage: Stage
    current_room: Room
    assigned_department: str
    patient: PatientMemory
    clinical: ClinicalState = Field(default_factory=ClinicalState)
    # Internal helper for scripted mock: where the current stage started in message history.
    stage_message_offset: int = 0


class EncounterResponse(EncounterState):
    can_interact: bool = False


class EncounterCreateResponse(EncounterState):
    can_interact: bool = False
    messages: List[Message] = Field(default_factory=list)


class ResetResponse(EncounterCreateResponse):
    pass


class MoveRequest(BaseModel):
    room: Room


class MoveResponse(BaseModel):
    encounter: EncounterResponse
    can_interact: bool
    suggested_next_action: Optional[str] = None


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class MessagesResponse(BaseModel):
    encounter: EncounterResponse
    messages: List[Message]
    can_interact: bool


def new_encounter_id() -> str:
    return str(uuid4())


def system_message(content: str) -> Message:
    return Message(id=str(uuid4()), role="system", content=content, created_at=utc_now_iso())

