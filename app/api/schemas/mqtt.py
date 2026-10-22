from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class DeviceCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command: str = Field(min_length=1, max_length=100)
    parameters: dict[str, object] = Field(default_factory=dict)


class DeviceCommandAccepted(BaseModel):
    device_id: UUID
    topic: str
    status: str
