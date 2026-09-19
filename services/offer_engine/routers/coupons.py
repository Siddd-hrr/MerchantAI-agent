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

router = APIRouter(prefix="/offers", tags=["offers-coupons"])


class CouponCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=500)
    condition: dict[str, Any] = Field(default_factory=dict)
    discount_type: Literal["PERCENT", "FLAT", "CASHBACK"]
    value: int = Field(ge=0)
    coupon_code: str = Field(min_length=1, max_length=64)
    item_ids: list[str] | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    is_active: bool = True


@router.post("/coupon")
async def create_coupon(
    payload: CouponCreateRequest,
    db_session: AsyncSession = Depends(get_offer_session_dependency),
    redis_client: Redis = Depends(get_offer_redis_dependency),
) -> dict[str, Any]:
    offer = Offer(
        offer_type="COUPON",
        name=payload.name,
        description=payload.description,
        item_ids=payload.item_ids,
        condition=payload.condition,
        discount_type=payload.discount_type,
        value=payload.value,
        coupon_code=payload.coupon_code.strip(),
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
        raise HTTPException(status_code=500, detail=f"Failed to create coupon offer: {exc}") from exc

    sync_result = await sync_offer_item_cache(redis_client, db_session, offer.item_ids)
    return build_offer_create_response(offer, sync_result)
