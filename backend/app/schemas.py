from pydantic import BaseModel, Field
from typing import Literal

LessonType = Literal["lecture", "seminar", "lab", "physical", "exam", "other"]

class UserPatch(BaseModel):
    name: str | None = None
    timezone: str | None = None
    home_address: str | None = None
    campus_name: str | None = None
    travel_minutes: int | None = Field(default=None, ge=0, le=300)
    prep_minutes: int | None = Field(default=None, ge=0, le=180)
    buffer_minutes: int | None = Field(default=None, ge=0, le=120)
    travel_mode: str | None = None

class LessonIn(BaseModel):
    subject: str = Field(min_length=1, max_length=180)
    lesson_type: LessonType = "lecture"
    weekday: int = Field(ge=0, le=6)
    start_time: str
    end_time: str
    room: str = ""
    campus: str = ""
    week_parity: str = "both"
    notes: str = ""

class BagRuleIn(BaseModel):
    match_type: Literal["always", "type", "keyword"] = "always"
    match_value: str = ""
    items: str = Field(min_length=1, max_length=2000)


class LessonParseIn(BaseModel):
    group_name: str = Field(min_length=1, max_length=100)
