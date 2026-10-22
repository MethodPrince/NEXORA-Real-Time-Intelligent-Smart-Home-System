from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator


class DeviceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    room: str | None = Field(default=None, max_length=120)
    device_type: str = Field(min_length=1, max_length=100)
    status: str = Field(default="unknown", min_length=1, max_length=100)
    online: bool = False


class DeviceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    room: str | None = Field(default=None, max_length=120)
    device_type: str | None = Field(default=None, min_length=1, max_length=100)
    status: str | None = Field(default=None, min_length=1, max_length=100)
    online: bool | None = None

    @model_validator(mode="after")
    def validate_patch_fields(self) -> "DeviceUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field_name in {"name", "device_type", "status", "online"}:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class DeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    room: str | None
    device_type: str
    status: str
    online: bool
    created_at: datetime
    updated_at: datetime
