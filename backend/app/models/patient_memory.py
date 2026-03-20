from pydantic import BaseModel, Field


class PatientMemory(BaseModel):
    name: str = "John Doe"
    age: int = 34
    gender: str = "M"
    chief_complaint: str = "Headache and mild fever"
    assigned_department: str = "Triage"

