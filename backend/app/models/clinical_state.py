from typing import List, Optional

from pydantic import BaseModel, Field


class ClinicalState(BaseModel):
    chief_complaint: str = "N/A"
    lab_results: List[str] = Field(default_factory=list)
    initial_diagnosis: Optional[str] = None
    prescription: Optional[str] = None

