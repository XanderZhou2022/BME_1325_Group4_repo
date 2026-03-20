from fastapi import APIRouter

from app.models.encounter import (
    EncounterResponse,
    EncounterCreateResponse,
    ResetResponse,
    MoveRequest,
    MoveResponse,
)
from app.services.encounter_service import encounter_service

router = APIRouter(prefix="/encounters", tags=["encounters"])


@router.post("", response_model=EncounterCreateResponse)
def create_encounter() -> EncounterCreateResponse:
    return encounter_service.create_encounter()


@router.get("/{encounter_id}", response_model=EncounterResponse)
def get_encounter(encounter_id: str) -> EncounterResponse:
    return encounter_service.get_encounter(encounter_id)


@router.post("/{encounter_id}/move", response_model=MoveResponse)
def move_encounter(encounter_id: str, body: MoveRequest) -> MoveResponse:
    return encounter_service.move(encounter_id=encounter_id, target_room=body.room)


@router.post("/{encounter_id}/order-test")
def order_test(encounter_id: str) -> dict:
    # Keep response flexible; frontend consumes structured fields.
    return encounter_service.order_test(encounter_id)


@router.post("/{encounter_id}/finish")
def finish(encounter_id: str) -> dict:
    return encounter_service.finish(encounter_id)


@router.post("/{encounter_id}/reset", response_model=ResetResponse)
def reset(encounter_id: str) -> ResetResponse:
    return encounter_service.reset(encounter_id)

