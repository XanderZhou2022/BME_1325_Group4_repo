from app.models.encounter import (
    EncounterResponse,
    EncounterCreateResponse,
    EncounterState,
    MoveResponse,
    MoveRequest,
    ResetResponse,
    Stage,
)
from app.models.encounter import new_encounter_id, system_message
from app.models.patient_memory import PatientMemory
from app.services.mock_clinical_service import mock_clinical_service
from app.services.dialogue_service import _room_for_stage, _to_encounter_response
from app.storage.in_memory_store import store
from app.models.message import Message
from app.models.clinical_state import ClinicalState


class EncounterService:
    def create_encounter(self) -> EncounterCreateResponse:
        encounter_id = new_encounter_id()
        encounter = EncounterState(
            id=encounter_id,
            status="in_progress",
            stage="triage",
            current_room="lobby",
            assigned_department="Triage",
            patient=PatientMemory(),
            clinical=ClinicalState(),
            stage_message_offset=0,
        )

        initial_messages: list[Message] = [
            system_message("Please go to the triage room."),
        ]

        store.create_encounter(encounter, initial_messages)
        return EncounterCreateResponse(
            **encounter.model_dump(),
            can_interact=False,
            messages=initial_messages,
        )

    def get_encounter(self, encounter_id: str) -> EncounterResponse:
        encounter = store.get_encounter(encounter_id)
        return _to_encounter_response(encounter)

    def get_messages(self, encounter_id: str):
        encounter = store.get_encounter(encounter_id)
        messages: list[Message] = store.get_messages(encounter_id)
        required_room = _room_for_stage(encounter.stage)
        can_interact = required_room is not None and encounter.current_room == required_room
        return {
            "encounter": _to_encounter_response(encounter),
            "messages": messages,
            "can_interact": can_interact,
        }

    def move(self, encounter_id: str, target_room: str) -> MoveResponse:
        encounter = store.get_encounter(encounter_id)
        messages: list[Message] = store.get_messages(encounter_id)

        # Validate room update (P0: allow moving freely; interaction is gated by can_interact)
        encounter.current_room = target_room  # type: ignore[assignment]

        required_room = _room_for_stage(encounter.stage)
        can_interact = required_room is not None and encounter.current_room == required_room
        suggested_next_action = None

        if can_interact:
            suggested_next_action = self._suggested_action_for_stage(encounter.stage)
            # Add a helpful system message only once per stage when user arrives early.
            patient_msgs_in_stage = sum(
                1
                for m in messages[encounter.stage_message_offset:]
                if m.role == "patient"
            )
            if patient_msgs_in_stage == 0:
                messages.append(
                    system_message(
                        f"You have arrived at the correct room. Now you can start the {encounter.stage} conversation."
                    )
                )

        store.set_encounter(encounter)
        store.set_messages(encounter_id, messages)

        return MoveResponse(
            encounter=_to_encounter_response(encounter),
            can_interact=can_interact,
            suggested_next_action=suggested_next_action,
        )

    def order_test(self, encounter_id: str) -> dict:
        encounter = store.get_encounter(encounter_id)
        messages: list[Message] = store.get_messages(encounter_id)

        if encounter.stage != "consultation" or encounter.current_room != "doctor_room":
            messages.append(
                system_message(
                    "Mock check can only be triggered in the doctor room during consultation."
                )
            )
            store.set_messages(encounter_id, messages)
            return {"error": "not_allowed"}

        clinical = mock_clinical_service.create_clinical_state_after_order_test()
        encounter.clinical = clinical

        # Add diagnosis and prescription messages.
        diagnosis = clinical.initial_diagnosis or "N/A"
        prescription = clinical.prescription or "N/A"

        messages.extend(
            [
                system_message("Mock exam completed."),
                Message(
                    id=f"doctor-dx-{len(messages)}",
                    role="doctor",
                    content=f"初步诊断（mock）：{diagnosis}",
                ),
                Message(
                    id=f"doctor-rx-{len(messages)+1}",
                    role="doctor",
                    content=f"处方建议（mock）：\n{prescription}",
                ),
                system_message("Please go to the pharmacy room."),
            ]
        )

        encounter.stage = "pharmacy"
        encounter.assigned_department = "Pharmacy"
        encounter.stage_message_offset = len(messages)

        store.set_encounter(encounter)
        store.set_messages(encounter_id, messages)

        return {
            "encounter": _to_encounter_response(encounter),
            "messages": messages,
        }

    def finish(self, encounter_id: str) -> dict:
        encounter = store.get_encounter(encounter_id)
        messages: list[Message] = store.get_messages(encounter_id)

        if encounter.stage != "pharmacy" or encounter.current_room != "pharmacy_room":
            messages.append(system_message("Please finish after you arrive in the pharmacy room."))
            store.set_messages(encounter_id, messages)
            return {"error": "not_allowed"}

        encounter.status = "completed"
        encounter.stage = "completed"

        messages.append(system_message("Thank you. This encounter is completed (mock)."))

        store.set_encounter(encounter)
        store.set_messages(encounter_id, messages)

        return {
            "encounter": _to_encounter_response(encounter),
            "messages": messages,
        }

    def reset(self, encounter_id: str) -> ResetResponse:
        # Reset on the same encounter id to keep frontend simple.
        encounter = EncounterState(
            id=encounter_id,
            status="in_progress",
            stage="triage",
            current_room="lobby",
            assigned_department="Triage",
            patient=PatientMemory(),
            clinical=ClinicalState(),
            stage_message_offset=0,
        )
        initial_messages: list[Message] = [system_message("Please go to the triage room.")]
        store.create_encounter(encounter, initial_messages)
        return ResetResponse(
            **encounter.model_dump(),
            can_interact=False,
            messages=initial_messages,
        )

    def _suggested_action_for_stage(self, stage: Stage) -> str:
        if stage == "triage":
            return "Talk to the triage nurse."
        if stage == "consultation":
            return "Consult the doctor and trigger a mock exam."
        if stage == "pharmacy":
            return "Read the prescription and finish."
        return "Encounter completed."


encounter_service = EncounterService()

