from pydantic import BaseModel, Field
from typing import List, Optional, Literal


class BaseDocument(BaseModel):
    id: str
    document_type: str
    priority: Optional[Literal["low", "medium", "high", "very_high"]] = "medium"


class ProfileDocument(BaseDocument):
    document_type: Literal["profile_summary"]

    name: str
    email: str
    location: str
    title: str

    first_person_summary: str
    third_person_summary: str

    core_focus: List[str]


