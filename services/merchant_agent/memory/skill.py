from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.memory import SkillMemory


class SkillMemoryStore:
    async def list_by_tool(self, db_session: AsyncSession, *, tool_name: str) -> list[dict[str, Any]]:
        rows = (
            await db_session.execute(select(SkillMemory).where(SkillMemory.tool_name == tool_name))
        ).scalars().all()
        return [
            {
                "tool_name": row.tool_name,
                "example_input": row.example_input,
                "example_output": row.example_output,
                "success": bool(row.success),
            }
            for row in rows
        ]

    async def create(
        self,
        db_session: AsyncSession,
        *,
        tool_name: str,
        example_input: dict[str, Any],
        example_output: dict[str, Any],
        success: bool = True,
    ) -> SkillMemory:
        row = SkillMemory(
            tool_name=tool_name,
            example_input=example_input,
            example_output=example_output,
            success=success,
        )
        db_session.add(row)
        await db_session.flush()
        return row

    async def delete(self, db_session: AsyncSession, *, tool_name: str) -> int:
        rows = (
            await db_session.execute(select(SkillMemory).where(SkillMemory.tool_name == tool_name))
        ).scalars().all()
        for row in rows:
            await db_session.delete(row)
        await db_session.flush()
        return len(rows)
