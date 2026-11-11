from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from app.db.models import HomeRole


class HomeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)


class HomeRead(BaseModel):
    id: UUID
    name: str
    role: HomeRole
