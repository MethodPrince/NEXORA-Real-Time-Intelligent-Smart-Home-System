from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from app.db.models import Device
from app.services.simulator import device_kind
from app.services.simulator import display_status
from app.services.simulator import is_simulated
from app.services.simulator import simulated_state


class DeviceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    room: str | None = Field(default=None, max_length=120)
    device_type: str = Field(min_length=1, max_length=100)
    status: str = Field(default="unknown", min_length=1, max_length=100)
    online: bool = False
    simulated: bool = False

    @model_validator(mode="after")
    def validate_simulated_device_type(self) -> "DeviceCreate":
        if self.simulated and device_kind(self.device_type) is None:
            raise ValueError("Simulated devices must be a light, fan, or curtain")
        return self


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

    @model_validator(mode="before")
    @classmethod
    def expose_simulated_state(cls, value: object) -> object:
        if not isinstance(value, Device):
            return value
        if not is_simulated(value):
            return value
        state = simulated_state(value)
        kind = device_kind(value.device_type)
        status = "Unavailable"
        if state is not None and kind is not None:
            status = display_status(kind, state)
        return {
            "id": value.id,
            "name": value.name,
            "room": value.room,
            "device_type": value.device_type,
            "status": status,
            "online": value.online,
            "created_at": value.created_at,
            "updated_at": value.updated_at,
            "simulated": True,
            "state": state,
        }

    id: UUID
    name: str
    room: str | None
    device_type: str
    status: str
    online: bool
    created_at: datetime
    updated_at: datetime
    simulated: bool = False
    state: dict[str, object] | None = None
