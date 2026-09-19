from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.models.audit_log import AuditLog
from shared.redis_client import get_redis_client


class MemoryStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.redis = get_redis_client()

    def _state_key(self, session_id: str) -> str:
        return f"session:{session_id}:state"

    def _draft_key(self, session_id: str) -> str:
        return f"session:{session_id}:order_draft"

    async def _touch_session_keys(self, session_id: str) -> None:
        ttl = self.settings.session_ttl_seconds
        await self.redis.expire(self._state_key(session_id), ttl)
        await self.redis.expire(self._draft_key(session_id), ttl)

    async def load_state(self, session_id: str) -> dict[str, Any] | None:
        raw = await self.redis.get(self._state_key(session_id))
        if not raw:
            return None
        await self._touch_session_keys(session_id)
        return json.loads(raw)

    async def load_order_draft(self, session_id: str) -> dict[str, Any] | None:
        raw = await self.redis.get(self._draft_key(session_id))
        if not raw:
            return None
        await self._touch_session_keys(session_id)
        return json.loads(raw)

    async def save_state(self, session_id: str, state: dict[str, Any]) -> None:
        ttl = self.settings.session_ttl_seconds
        await self.redis.set(self._state_key(session_id), json.dumps(state), ex=ttl)
        draft = {
            "line_items": state.get("line_items", []),
            "customer_name": state.get("customer_name"),
            "address": state.get("address"),
            "phone": state.get("phone"),
            "mandate_verified": state.get("mandate_verified", False),
            "missing_fields": state.get("missing_fields", []),
            "status": state.get("status"),
        }
        await self.redis.set(self._draft_key(session_id), json.dumps(draft), ex=ttl)

    async def append_audit(
        self,
        db_session: AsyncSession,
        *,
        session_id: str,
        actor: str,
        action: str,
        detail: dict[str, Any],
    ) -> None:
        db_session.add(
            AuditLog(
                session_id=session_id,
                actor=actor,
                action=action,
                detail=detail,
            )
        )
        await db_session.flush()
        await self.redis.xadd(
            "audit:stream",
            {
                "session_id": session_id,
                "actor": actor,
                "action": action,
                "detail": json.dumps(detail),
            },
        )
