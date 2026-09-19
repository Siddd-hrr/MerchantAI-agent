from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.offer_engine.availability_client import AvailabilityClient, AvailabilityLookupError
from services.offer_engine.routers.common import (
    get_availability_client_dependency,
    get_offer_session_dependency,
)
from shared.models.cross_sell import CrossSellPreference

router = APIRouter(prefix="/offers", tags=["offers-cross-sell"])


class CrossSellCreateRequest(BaseModel):
    source_item_id: UUID
    target_item_ids: list[UUID] = Field(min_length=1)
    priority: int = Field(default=0, ge=0)
    is_active: bool = True


def _serialize_cross_sell(preference: CrossSellPreference) -> dict[str, Any]:
    return {
        "id": str(preference.id),
        "source_item_id": str(preference.source_item_id),
        "target_item_ids": preference.target_item_ids,
        "priority": preference.priority,
        "is_active": bool(preference.is_active),
    }


@router.get("/cross-sell")
async def list_cross_sell(
    include_inactive: bool = Query(default=False),
    db_session: AsyncSession = Depends(get_offer_session_dependency),
) -> dict[str, Any]:
    stmt = select(CrossSellPreference).order_by(
        CrossSellPreference.priority.desc(),
        CrossSellPreference.id.desc(),
    )
    if not include_inactive:
        stmt = stmt.where(CrossSellPreference.is_active.is_(True))
    rows = (await db_session.execute(stmt)).scalars().all()
    return {"count": len(rows), "cross_sells": [_serialize_cross_sell(row) for row in rows]}


@router.delete("/cross-sell/{preference_id}")
async def terminate_cross_sell(
    preference_id: UUID,
    db_session: AsyncSession = Depends(get_offer_session_dependency),
) -> dict[str, Any]:
    preference = (
        await db_session.execute(
            select(CrossSellPreference).where(CrossSellPreference.id == preference_id)
        )
    ).scalar_one_or_none()
    if preference is None:
        raise HTTPException(status_code=404, detail="Cross-sell preference not found")
    if not preference.is_active:
        return {
            "status": "ok",
            "message": "Cross-sell already terminated",
            "cross_sell_preference": _serialize_cross_sell(preference),
        }

    preference.is_active = False
    try:
        await db_session.commit()
        await db_session.refresh(preference)
    except Exception as exc:  # noqa: BLE001
        await db_session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to terminate cross-sell: {exc}") from exc

    return {
        "status": "ok",
        "message": "Cross-sell terminated",
        "cross_sell_preference": _serialize_cross_sell(preference),
    }


@router.post("/cross-sell")
async def create_cross_sell(
    payload: CrossSellCreateRequest,
    db_session: AsyncSession = Depends(get_offer_session_dependency),
    availability_client: AvailabilityClient = Depends(get_availability_client_dependency),
) -> dict[str, Any]:
    item_ids_to_validate = [
        str(payload.source_item_id),
        *(str(target_item_id) for target_item_id in payload.target_item_ids),
    ]
    try:
        true_available_by_item_id = await availability_client.get_true_available_qty_map(
            item_ids_to_validate,
            raise_on_error=True,
        )
    except AvailabilityLookupError as exc:
        raise HTTPException(status_code=503, detail=f"Could not verify true availability: {exc}") from exc

    unavailable_item_ids = [
        item_id for item_id in item_ids_to_validate if int(true_available_by_item_id.get(item_id, 0)) <= 0
    ]
    if unavailable_item_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ITEM_TRUE_AVAILABILITY_ZERO",
                "message": "Cross-sell cannot include items with zero true available quantity.",
                "item_ids": unavailable_item_ids,
            },
        )

    preference = CrossSellPreference(
        source_item_id=payload.source_item_id,
        target_item_ids=[str(target_item_id) for target_item_id in payload.target_item_ids],
        priority=payload.priority,
        is_active=payload.is_active,
    )
    db_session.add(preference)
    try:
        await db_session.commit()
        await db_session.refresh(preference)
    except Exception as exc:  # noqa: BLE001
        await db_session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create cross-sell preference: {exc}") from exc

    return {
        "status": "ok",
        "cross_sell_preference": _serialize_cross_sell(preference),
    }
