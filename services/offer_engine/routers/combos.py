from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from services.offer_engine.availability_client import AvailabilityClient, AvailabilityLookupError
from services.offer_engine.redis_sync import sync_offer_item_cache
from services.offer_engine.routers.common import (
    get_availability_client_dependency,
    build_offer_create_response,
    get_offer_redis_dependency,
    get_offer_session_dependency,
)
from shared.models.offer import Offer

router = APIRouter(prefix="/offers", tags=["offers-combos"])


class ComboCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=500)
    item_ids: list[str] = Field(min_length=1)
    combo_with_item_ids: list[str] = Field(min_length=1)
    condition: dict[str, Any] = Field(default_factory=dict)
    discount_type: Literal["PERCENT", "FLAT", "CASHBACK"]
    value: int = Field(ge=0)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    is_active: bool = True


@router.post("/combo")
async def create_combo(
    payload: ComboCreateRequest,
    db_session: AsyncSession = Depends(get_offer_session_dependency),
    redis_client: Redis = Depends(get_offer_redis_dependency),
    availability_client: AvailabilityClient = Depends(get_availability_client_dependency),
) -> dict[str, Any]:
    combo_item_ids = list(dict.fromkeys(payload.item_ids + payload.combo_with_item_ids))
    try:
        true_available_by_item_id = await availability_client.get_true_available_qty_map(
            combo_item_ids,
            raise_on_error=True,
        )
    except AvailabilityLookupError as exc:
        raise HTTPException(status_code=503, detail=f"Could not verify true availability: {exc}") from exc

    unavailable_item_ids = [item_id for item_id in combo_item_ids if int(true_available_by_item_id.get(item_id, 0)) <= 0]
    if unavailable_item_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ITEM_TRUE_AVAILABILITY_ZERO",
                "message": "Combo cannot include items with zero true available quantity.",
                "item_ids": unavailable_item_ids,
            },
        )

    offer = Offer(
        offer_type="COMBO",
        name=payload.name,
        description=payload.description,
        item_ids=payload.item_ids,
        condition=payload.condition,
        discount_type=payload.discount_type,
        value=payload.value,
        combo_with_item_ids=payload.combo_with_item_ids,
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
        raise HTTPException(status_code=500, detail=f"Failed to create combo offer: {exc}") from exc

    sync_item_ids = list(set(payload.item_ids + payload.combo_with_item_ids))
    sync_result = await sync_offer_item_cache(redis_client, db_session, sync_item_ids)
    return build_offer_create_response(offer, sync_result)
