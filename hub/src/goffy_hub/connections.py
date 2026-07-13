from __future__ import annotations

import asyncio
from contextlib import suppress
from uuid import UUID

from fastapi import WebSocket


class WebSocketConnectionRegistry:
    """Indexes live paired WebSockets so credential revocation is immediate."""

    def __init__(self) -> None:
        self._connections: dict[UUID, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def register(self, credential_id: UUID, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.setdefault(credential_id, set()).add(websocket)

    async def unregister(self, credential_id: UUID, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(credential_id)
            if connections is None:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(credential_id, None)

    async def revoke(self, credential_id: UUID) -> None:
        async with self._lock:
            connections = tuple(self._connections.pop(credential_id, ()))

        async def close(websocket: WebSocket) -> None:
            with suppress(Exception):
                await websocket.close(code=4403, reason="credential revoked")

        await asyncio.gather(*(close(websocket) for websocket in connections))
