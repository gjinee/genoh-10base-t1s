"""WebSocket connection manager for real-time GUI updates."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

from gui.common.protocol import WSMessage

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        logger.info("WebSocket connected (%d total)", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        logger.info("WebSocket disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, message: WSMessage) -> None:
        raw = message.to_json()
        async with self._lock:
            dead: list[WebSocket] = []
            for ws in self._connections:
                try:
                    await ws.send_text(raw)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections.remove(ws)

    async def send_personal(self, ws: WebSocket, message: WSMessage) -> None:
        try:
            await ws.send_text(message.to_json())
        except Exception:
            await self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._connections)
