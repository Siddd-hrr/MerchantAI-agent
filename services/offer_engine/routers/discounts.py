from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from services.offer_engine.redis_sync import sync_offer_item_cache
from services.offer_engine.routers.common import (
    build_offer_create_response,
    get_offer_redis_dependency,
    get_offer_session_dependency,
)
from shared.models.offer import Offer

router = APIRouter(prefix="/offers", tags=["offers-discounts"])


class DiscountCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=500)
    item_ids: list[str] = Field(default_factory=list)
    condition: dict[str, Any] = Field(default_factory=dict)
    discount_type: Literal["PERCENT", "FLAT", "CASHBACK"]
    value: int = Field(ge=0)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    is_active: bool = True


@router.post("/discount")
async def create_discount(
    payload: DiscountCreateRequest,
    db_session: AsyncSession = Depends(get_offer_session_dependency),
    redis_client: Redis = Depends(get_offer_redis_dependency),
) -> dict[str, Any]:
    offer = Offer(
        offer_type="DISCOUNT",
        name=payload.name,
        description=payload.description,
        item_ids=payload.item_ids or None,
        condition=payload.condition,
        discount_type=payload.discount_type,
        value=payload.value,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        is_active=payload.is_active,
    )
    db_session.add(offer)
    try:
        await db_session.commit()
        await db_session.refresh(offer)
    except Exception as exc:  # noqa: BLE001
        await db_session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create discount offer: {exc}") from exc

    sync_result = await sync_offer_item_cache(redis_client, db_session, offer.item_ids)
    return build_offer_create_response(offer, sync_result)
