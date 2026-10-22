from datetime import datetime
from datetime import timezone
from typing import Literal

from pydantic import BaseModel


class SystemEvent(BaseModel):
    type: Literal["system_event"] = "system_event"
    source: str = "nexora_backend"
    message: str
    timestamp: datetime

    @classmethod
    def test_event(cls) -> "SystemEvent":
        return cls(
            message="NEXORA real-time system is working",
            timestamp=datetime.now(timezone.utc),
        )
