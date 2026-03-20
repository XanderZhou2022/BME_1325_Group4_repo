from typing import Dict

from app.models.encounter import EncounterState


class InMemoryStore:
    """
    Very small in-memory store for demo only.

    This is intentionally not thread-safe or persistent.
    """

    def __init__(self) -> None:
        self._encounters: Dict[str, EncounterState] = {}
        self._messages: Dict[str, list] = {}

    def create_encounter(self, encounter: EncounterState, messages: list) -> None:
        self._encounters[encounter.id] = encounter
        self._messages[encounter.id] = list(messages)

    def get_encounter(self, encounter_id: str) -> EncounterState:
        if encounter_id not in self._encounters:
            raise KeyError(f"Encounter not found: {encounter_id}")
        return self._encounters[encounter_id]

    def set_encounter(self, encounter: EncounterState) -> None:
        self._encounters[encounter.id] = encounter

    def get_messages(self, encounter_id: str) -> list:
        return list(self._messages.get(encounter_id, []))

    def set_messages(self, encounter_id: str, messages: list) -> None:
        self._messages[encounter_id] = list(messages)

    def clear(self) -> None:
        self._encounters.clear()
        self._messages.clear()


store = InMemoryStore()

