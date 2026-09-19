from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.memory import ProceduralMemory


class ProceduralMemoryStore:
    async def get(self, db_session: AsyncSession, *, playbook_name: str) -> dict[str, Any] | None:
        row = (
            await db_session.execute(
                select(ProceduralMemory).where(ProceduralMemory.playbook_name == playbook_name)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return {"playbook_name": row.playbook_name, "steps": row.steps, "version": int(row.version)}

    async def list_all(self, db_session: AsyncSession) -> list[dict[str, Any]]:
        rows = (await db_session.execute(select(ProceduralMemory))).scalars().all()
        return [{"playbook_name": row.playbook_name, "steps": row.steps, "version": int(row.version)} for row in rows]

    async def upsert(
        self,
        db_session: AsyncSession,
        *,
        playbook_name: str,
        steps: list[dict[str, Any]],
        version: int = 1,
    ) -> ProceduralMemory:
        row = (
            await db_session.execute(
                select(ProceduralMemory).where(ProceduralMemory.playbook_name == playbook_name)
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProceduralMemory(playbook_name=playbook_name, steps=steps, version=version)
            db_session.add(row)
        else:
            row.steps = steps
            row.version = version
        await db_session.flush()
        return row

    async def delete(self, db_session: AsyncSession, *, playbook_name: str) -> bool:
        row = (
            await db_session.execute(
                select(ProceduralMemory).where(ProceduralMemory.playbook_name == playbook_name)
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        await db_session.delete(row)
        await db_session.flush()
        return True
