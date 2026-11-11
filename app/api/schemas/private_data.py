from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict


class SensorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    sensor_type: str
    device_id: UUID
    reading: float | None
    unit: str | None
    timestamp: datetime


class ActivityLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str
    device_id: UUID | None
    event: str
    action: str | None
    result: str | None
    timestamp: datetime
