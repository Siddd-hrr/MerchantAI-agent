from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.cross_sell import CrossSellPreference


class CrossSellLookupTool:
    async def for_item(self, db_session: AsyncSession, item_id: str) -> list[dict[str, Any]]:
        try:
            normalized_item_id = UUID(item_id)
        except ValueError:
            return []
        row = (
            await db_session.execute(
                select(CrossSellPreference)
                .where(
                    CrossSellPreference.source_item_id == normalized_item_id,
                    CrossSellPreference.is_active.is_(True),
                )
                .order_by(CrossSellPreference.priority.desc())
            )
        ).scalar_one_or_none()
        if row is None:
            return []
        return [
            {
                "source_item_id": str(row.source_item_id),
                "target_item_ids": row.target_item_ids,
                "priority": int(row.priority),
            }
        ]
