from __future__ import annotations

from typing import Any

from services.merchant_agent.memory_store import MemoryStore


class ShortTermMemory:
    """Thin wrapper over existing Redis-backed MemoryStore."""

    def __init__(self, memory_store: MemoryStore) -> None:
        self._memory_store = memory_store

    async def load_state(self, session_id: str) -> dict[str, Any] | None:
        return await self._memory_store.load_state(session_id)

    async def load_order_draft(self, session_id: str) -> dict[str, Any] | None:
        return await self._memory_store.load_order_draft(session_id)

    async def save_state(self, session_id: str, state: dict[str, Any]) -> None:
        await self._memory_store.save_state(session_id, state)
