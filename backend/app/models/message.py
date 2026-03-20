from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["system", "patient", "nurse", "doctor", "pharmacist"]

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Message(BaseModel):
    id: str
    role: Role
    content: str
    created_at: str = Field(
        default_factory=utc_now_iso,
        description="ISO-8601 timestamp in UTC",
        examples=["2026-03-20T06:00:00Z"],
    )

