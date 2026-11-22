import re
from pydantic import BaseModel, Field, field_validator
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

    @field_validator("home_address")
    @classmethod
    def city_in_russian(cls, v):
        v = (v or "").strip()
        if v and re.search(r"[A-Za-z]", v):
            raise ValueError("Введите город на русском языке, например: Санкт-Петербург")
        return v

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

class ChatSettingsIn(BaseModel):
    enabled: bool | None = None
    custom_rules: str | None = Field(default=None, max_length=4000)
    digest_mode: Literal["off", "daily", "weekly"] | None = None
    digest_hour: int | None = Field(default=None, ge=0, le=23)
    external_ai_enabled: bool | None = None

class AISettingsIn(BaseModel):
    mode: Literal["economy", "auto", "quality"] | None = None
    ai_enabled: bool | None = None

class MonitorRuleIn(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    chat_id: int | None = None
    priority: Literal["low", "normal", "high"] = "normal"
    cooldown_minutes: int = Field(default=60, ge=5, le=10080)

class AgentChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    chat_ids: list[int] = Field(default_factory=list, max_length=20)
    detail: Literal["brief", "normal", "detailed"] = "normal"
