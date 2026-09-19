from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_db_session
from shared.models.item import Item
from shared.redis_client import close_redis_client, get_redis_client

router = APIRouter(tags=["internal-inventory"])


async def get_redis_dependency() -> AsyncGenerator[Redis, None]:
    redis_client = get_redis_client()
    try:
        yield redis_client
    finally:
        await close_redis_client(redis_client)


@router.get("/internal/items/{item_id}/true-available")
async def get_true_available(
    item_id: UUID,
    db_session: AsyncSession = Depends(get_db_session),
    redis_client: Redis = Depends(get_redis_dependency),
) -> dict[str, int | str]:
    item = (await db_session.execute(select(Item).where(Item.id == item_id, Item.is_active.is_(True)))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Item {item_id} not found")

    key = f"reserved:item:{item_id}"
    reserved_qty = int((await redis_client.get(key)) or 0)
    quantity_available = int(item.quantity_available)
    return {
        "item_id": str(item_id),
        "true_available_qty": quantity_available - reserved_qty,
        "quantity_available": quantity_available,
        "reserved_qty": reserved_qty,
    }
