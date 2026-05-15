from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CompassionDraftRequest(BaseModel):
    admission_id: str
    draft_type: str = "daily_family_update_draft"


class CompassionDraftResponse(BaseModel):
    schema_version: str = "compassion_family_communication.v1"
    agent_name: str = "compassion_family_communication"
    admission_id: str
    patient_id: str
    bed_id: str
    draft_type: str
    clinician_review_version: str
    family_plain_language_draft: str
    icu_diary_draft: str | None = None
    communication_cautions: list[str] = []
    what_not_to_say: list[str] = []
    supporting_card_ids: list[str] = []
    knowledge_context: list[dict[str, Any]] = []
    forbidden_use_reminder: list[str] = []
    requires_clinician_approval_before_delivery: bool = True
    generated_at: datetime
    knowledge_used: bool = False
    llm_used: bool = False
    fallback_used: bool = True
    audit_log_id: str | None = None
    human_review_required: bool = True
