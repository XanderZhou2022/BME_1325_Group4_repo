from app.models.encounter import (
    EncounterResponse,
    MessagesResponse,
    EncounterState,
    Room,
    Stage,
)
from app.models.message import Message
from app.models.encounter import system_message
from app.storage.in_memory_store import store


def _room_for_stage(stage: Stage) -> Room | None:
    if stage == "triage":
        return "triage_room"
    if stage == "consultation":
        return "doctor_room"
    if stage == "pharmacy":
        return "pharmacy_room"
    return None


def _interaction_role_for_stage(stage: Stage) -> str | None:
    if stage == "triage":
        return "nurse"
    if stage == "consultation":
        return "doctor"
    if stage == "pharmacy":
        return "pharmacist"
    return None


def _patient_message_count_in_current_stage(
    messages: list[Message], stage_message_offset: int
) -> int:
    return sum(1 for m in messages[stage_message_offset:] if m.role == "patient")


class DialogueService:
    def send_patient_message(
        self, encounter_id: str, patient_message: str
    ) -> MessagesResponse:
        encounter = store.get_encounter(encounter_id)
        messages: list[Message] = store.get_messages(encounter_id)

        stage = encounter.stage
        required_room = _room_for_stage(stage)
        can_interact = required_room is not None and encounter.current_room == required_room

        if encounter.status != "in_progress" or stage == "completed":
            added = [
                system_message(
                    "This encounter is already completed. Click “重新开始” to start again."
                )
            ]
            messages.extend(added)
            store.set_messages(encounter_id, messages)
            return MessagesResponse(
                encounter=_to_encounter_response(encounter),
                messages=messages,
                can_interact=False,
            )

        # Save patient message first.
        patient_msg_obj = Message(
            id=f"patient-{len(messages)}",
            role="patient",
            content=patient_message,
        )
        messages.append(patient_msg_obj)

        added: list[Message] = []

        if not can_interact:
            added.append(
                system_message(
                    "You can only talk in the correct room. "
                    f"Please go to the {required_room.replace('_', ' ')}."
                )
            )
            messages.extend(added)
            store.set_messages(encounter_id, messages)
            return MessagesResponse(
                encounter=_to_encounter_response(encounter),
                messages=messages,
                can_interact=False,
            )

        # Scripted mock dialogue per stage.
        patient_count = _patient_message_count_in_current_stage(
            messages, encounter.stage_message_offset
        )
        if stage == "triage":
            # patient_count includes the newly appended one.
            if patient_count == 1:
                added.append(
                    Message(
                        id=f"nurse-{len(messages)}",
                        role="nurse",
                        content="您好，我是分诊护士。请描述您的主要不适以及持续多久了？",
                    )
                )
            elif patient_count == 2:
                # Move to consultation stage.
                encounter.stage = "consultation"
                encounter.assigned_department = "Internal Medicine"
                added.append(
                    Message(
                        id=f"nurse-{len(messages)}",
                        role="nurse",
                        content=(
                            "根据您的描述，我将您分配到医生诊室（内科）。"
                            "请现在前往医生诊室开始咨询。"
                        ),
                    )
                )
                added.append(system_message("Please go to the doctor room."))
            else:
                added.append(
                    Message(
                        id=f"nurse-{len(messages)}",
                        role="nurse",
                        content="目前分诊已完成。请前往医生诊室。点击房间或继续按提示操作即可。",
                    )
                )

        elif stage == "consultation":
            if patient_count == 1:
                added.append(
                    Message(
                        id=f"doctor-{len(messages)}",
                        role="doctor",
                        content="好的。我想了解一下：不适位置在哪里？大概疼痛/不适程度如何（轻/中/重）？",
                    )
                )
            elif patient_count == 2:
                added.append(
                    Message(
                        id=f"doctor-{len(messages)}",
                        role="doctor",
                        content="了解了。我将触发一次 mock 检查以辅助评估。请点击按钮“触发一次检查”。",
                    )
                )
                added.append(system_message("Doctor is preparing an exam. Click “触发一次检查”。"))
            else:
                added.append(
                    Message(
                        id=f"doctor-{len(messages)}",
                        role="doctor",
                        content="请先点击“触发一次检查”。检查完成后会进入取药流程。",
                    )
                )

        elif stage == "pharmacy":
            if patient_count == 1:
                added.append(
                    Message(
                        id=f"pharm-{len(messages)}",
                        role="pharmacist",
                        content=(
                            "处方已准备。请阅读药品说明并按医嘱服用（mock）。"
                            "你需要我再解释用法吗？"
                        ),
                    )
                )
            else:
                added.append(
                    Message(
                        id=f"pharm-{len(messages)}",
                        role="pharmacist",
                        content="好的。祝你早日康复。点击“完成就诊”结束本次流程。",
                    )
                )
        else:
            added.append(system_message("Unknown stage."))

        messages.extend(added)

        # If stage changed, reset stage_message_offset for the next stage.
        # We detect this by comparing the required room at the time we sent the first response.
        if encounter.stage != stage:
            # stage_message_offset should start *after* the messages we just appended.
            encounter.stage_message_offset = len(messages)

        # Persist any stage changes.
        store.set_encounter(encounter)
        store.set_messages(encounter_id, messages)

        required_room_after = _room_for_stage(encounter.stage)
        can_interact_after = (
            required_room_after is not None and encounter.current_room == required_room_after
        )

        return MessagesResponse(
            encounter=_to_encounter_response(encounter),
            messages=messages,
            can_interact=can_interact_after,
        )


def _to_encounter_response(encounter: EncounterState) -> EncounterResponse:
    required_room = _room_for_stage(encounter.stage)
    can_interact = required_room is not None and encounter.current_room == required_room
    return EncounterResponse(
        **encounter.model_dump(),
        can_interact=can_interact,
    )


dialogue_service = DialogueService()

