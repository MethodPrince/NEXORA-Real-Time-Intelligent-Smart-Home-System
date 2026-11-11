from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import EmailStr
from pydantic import Field
from pydantic import model_validator

from app.db.models import UserRole


class AdminUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.STANDARD_USER

class AdminUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: UserRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_update(self) -> "AdminUserUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field in ("role", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class DeviceGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: UUID
    can_control: bool = False


class DeviceGrantList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grants: list[DeviceGrant] = Field(max_length=500)

    @model_validator(mode="after")
    def require_unique_devices(self) -> "DeviceGrantList":
        device_ids = [grant.device_id for grant in self.grants]
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("Each device may only appear once")
        return self


class DeviceGrantRead(DeviceGrant):
    name: str
    room: str | None
    device_type: str


class SecuritySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registration_enabled: bool
