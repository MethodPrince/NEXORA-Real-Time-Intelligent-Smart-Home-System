from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator


class ScheduleTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["schedule"] = "schedule"
    time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(min_length=1, max_length=100)
    days: list[int] = Field(min_length=1, max_length=7)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("timezone must be a valid IANA timezone") from error
        return value

    @field_validator("days")
    @classmethod
    def validate_days(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("days must be between 0 (Monday) and 6 (Sunday)")
        if len(set(value)) != len(value):
            raise ValueError("days cannot contain duplicates")
        return value


class AutomationAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    device_id: UUID
    command: Literal["turn_on", "turn_off", "open", "close"]


class AutomationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    trigger: ScheduleTrigger
    action: AutomationAction
    enabled: bool = True


class AutomationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    trigger: ScheduleTrigger | None = None
    action: AutomationAction | None = None
    enabled: bool | None = None


class AutomationRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    trigger: ScheduleTrigger
    action: AutomationAction
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
