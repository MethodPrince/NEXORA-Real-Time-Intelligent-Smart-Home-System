import asyncio
import logging

from fastapi import WebSocket
from fastapi import WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.active_connections.discard(websocket)

    async def send_personal_message(
        self,
        message: str,
        websocket: WebSocket,
    ) -> None:
        try:
            await websocket.send_text(message)
        except (WebSocketDisconnect, RuntimeError):
            logger.warning("Unable to send to disconnected WebSocket client")
            await self.disconnect(websocket)

    async def broadcast(self, event: dict[str, str]) -> None:
        async with self._lock:
            connections = tuple(self.active_connections)

        await asyncio.gather(
            *(self._send_event(websocket, event) for websocket in connections)
        )

    async def _send_event(
        self,
        websocket: WebSocket,
        event: dict[str, str],
    ) -> None:
        try:
            await websocket.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            logger.warning("Unable to broadcast to disconnected WebSocket client")
            await self.disconnect(websocket)


connection_manager = ConnectionManager()
