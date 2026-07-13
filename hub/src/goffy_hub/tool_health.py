from __future__ import annotations

import asyncio
import logging

from goffy_hub.registry import ToolHealthReport, ToolRegistry

LOGGER = logging.getLogger(__name__)


class ToolHealthMonitor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        interval_seconds: float,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("health interval must be positive")
        self._registry = registry
        self._interval_seconds = interval_seconds
        self._check_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> ToolHealthReport:
        async with self._check_lock:
            report = await self._registry.refresh_health()
            self._initialized = True
            return report

    async def check_now(self) -> ToolHealthReport:
        if not self._initialized:
            return await self.initialize()
        async with self._check_lock:
            try:
                return await self._registry.refresh_health()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.error("Tool health monitor failed; all tools are unavailable")
                return await self._registry.mark_all_unavailable()

    async def run(self) -> None:
        if not self._initialized:
            await self.initialize()
        while True:
            await asyncio.sleep(self._interval_seconds)
            await self.check_now()
