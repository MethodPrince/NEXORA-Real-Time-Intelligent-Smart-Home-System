import asyncio
import logging
from collections.abc import Iterable
from uuid import UUID

from fastapi import WebSocket
from fastapi import WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[tuple[UUID, UUID], set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        user_id: UUID,
        home_id: UUID,
    ) -> None:
        await websocket.accept(subprotocol="nexora")
        async with self._lock:
            self.active_connections.setdefault((home_id, user_id), set()).add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            for key, connections in tuple(self.active_connections.items()):
                connections.discard(websocket)
                if not connections:
                    del self.active_connections[key]

    async def disconnect_user(self, user_id: UUID) -> None:
        async with self._lock:
            connections = tuple(
                websocket
                for (home_id, connected_user_id), sockets in tuple(self.active_connections.items())
                if connected_user_id == user_id
                for websocket in sockets
            )
            for key in tuple(self.active_connections):
                if key[1] == user_id:
                    del self.active_connections[key]
        await asyncio.gather(
            *(self._close_connection(websocket) for websocket in connections)
        )

    async def disconnect_user_home(self, user_id: UUID, home_id: UUID) -> None:
        async with self._lock:
            connections = tuple(self.active_connections.pop((home_id, user_id), ()))
        await asyncio.gather(
            *(self._close_connection(websocket) for websocket in connections)
        )

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

    async def broadcast_to_user(
        self,
        home_id: UUID,
        user_id: UUID,
        event: dict[str, object],
    ) -> None:
        await self._broadcast_to_home_user(home_id, user_id, event)

    async def broadcast_to_home_users(
        self,
        home_id: UUID,
        user_ids: Iterable[UUID],
        event: dict[str, object],
    ) -> None:
        await asyncio.gather(
            *(self._broadcast_to_home_user(home_id, user_id, event) for user_id in set(user_ids))
        )

    async def broadcast_to_home(
        self,
        home_id: UUID,
        event: dict[str, object],
    ) -> None:
        async with self._lock:
            connections = tuple(
                websocket
                for (connected_home_id, _user_id), sockets in self.active_connections.items()
                if connected_home_id == home_id
                for websocket in sockets
            )
        await asyncio.gather(
            *(self._send_event(websocket, event) for websocket in connections)
        )

    async def _broadcast_to_home_user(
        self,
        home_id: UUID,
        user_id: UUID,
        event: dict[str, object],
    ) -> None:
        async with self._lock:
            connections = tuple(self.active_connections.get((home_id, user_id), ()))
        await asyncio.gather(
            *(self._send_event(websocket, event) for websocket in connections)
        )

    async def _send_event(
        self,
        websocket: WebSocket,
        event: dict[str, object],
    ) -> None:
        try:
            await websocket.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            logger.warning("Unable to broadcast to disconnected WebSocket client")
            await self.disconnect(websocket)

    async def _close_connection(self, websocket: WebSocket) -> None:
        try:
            await websocket.close(code=4403, reason="Account is inactive")
        except (WebSocketDisconnect, RuntimeError):
            logger.warning("Unable to close inactive user's WebSocket")


connection_manager = ConnectionManager()
