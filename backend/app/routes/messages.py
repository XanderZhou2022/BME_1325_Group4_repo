from fastapi import APIRouter

from app.models.encounter import (
    MessagesResponse,
    MessageCreateRequest,
)
from app.services.encounter_service import encounter_service
from app.services.dialogue_service import dialogue_service

router = APIRouter(prefix="/encounters", tags=["messages"])


@router.get("/{encounter_id}/messages", response_model=MessagesResponse)
def get_messages(encounter_id: str) -> MessagesResponse:
    return encounter_service.get_messages(encounter_id)


@router.post("/{encounter_id}/messages", response_model=MessagesResponse)
def post_message(encounter_id: str, body: MessageCreateRequest) -> MessagesResponse:
    return dialogue_service.send_patient_message(
        encounter_id=encounter_id, patient_message=body.content
    )

