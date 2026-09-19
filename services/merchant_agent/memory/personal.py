from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.memory import PersonalMemory


class PersonalMemoryStore:
    async def get(self, db_session: AsyncSession, *, consumer_agent_id: str, key: str) -> dict[str, Any] | None:
        row = (
            await db_session.execute(
                select(PersonalMemory).where(
                    PersonalMemory.consumer_agent_id == consumer_agent_id,
                    PersonalMemory.key == key,
                )
            )
        ).scalar_one_or_none()
        return row.value if row else None

    async def list_by_consumer(
        self, db_session: AsyncSession, *, consumer_agent_id: str
    ) -> dict[str, dict[str, Any]]:
        rows = (
            await db_session.execute(
                select(PersonalMemory).where(PersonalMemory.consumer_agent_id == consumer_agent_id)
            )
        ).scalars().all()
        return {row.key: row.value for row in rows}

    async def upsert(
        self,
        db_session: AsyncSession,
        *,
        consumer_agent_id: str,
        key: str,
        value: dict[str, Any],
    ) -> PersonalMemory:
        row = (
            await db_session.execute(
                select(PersonalMemory).where(
                    PersonalMemory.consumer_agent_id == consumer_agent_id,
                    PersonalMemory.key == key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = PersonalMemory(consumer_agent_id=consumer_agent_id, key=key, value=value)
            db_session.add(row)
        else:
            row.value = value
        await db_session.flush()
        return row

    async def delete(self, db_session: AsyncSession, *, consumer_agent_id: str, key: str) -> bool:
        row = (
            await db_session.execute(
                select(PersonalMemory).where(
                    PersonalMemory.consumer_agent_id == consumer_agent_id,
                    PersonalMemory.key == key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        await db_session.delete(row)
        await db_session.flush()
        return True
