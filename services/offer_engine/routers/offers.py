from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.offer_engine.redis_sync import offer_item_key, serialize_offer, sync_offer_item_cache
from services.offer_engine.routers.common import get_offer_redis_dependency, get_offer_session_dependency
from shared.models.offer import Offer

router = APIRouter(prefix="/offers", tags=["offers-read"])


@router.get("/saved")
async def list_saved_offers(
    offer_type: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    db_session: AsyncSession = Depends(get_offer_session_dependency),
) -> dict[str, Any]:
    stmt = select(Offer).order_by(Offer.created_at.desc())
    if not include_inactive:
        stmt = stmt.where(Offer.is_active.is_(True))
    if offer_type:
        stmt = stmt.where(Offer.offer_type == offer_type.upper())
    offers = (await db_session.execute(stmt)).scalars().all()
    return {"count": len(offers), "offers": [serialize_offer(offer) for offer in offers]}


@router.delete("/{offer_id}")
async def terminate_offer(
    offer_id: UUID,
    db_session: AsyncSession = Depends(get_offer_session_dependency),
    redis_client: Redis = Depends(get_offer_redis_dependency),
) -> dict[str, Any]:
    offer = (
        await db_session.execute(select(Offer).where(Offer.id == offer_id))
    ).scalar_one_or_none()
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not offer.is_active:
        return {"status": "ok", "message": "Offer already terminated", "offer": serialize_offer(offer)}

    offer.is_active = False
    affected_item_ids = list(
        {
            *(offer.item_ids or []),
            *(offer.combo_with_item_ids or []),
        }
    )
    try:
        await db_session.commit()
        await db_session.refresh(offer)
    except Exception as exc:  # noqa: BLE001
        await db_session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to terminate offer: {exc}") from exc

    sync_result = await sync_offer_item_cache(redis_client, db_session, affected_item_ids)
    return {
        "status": "ok",
        "message": "Offer terminated",
        "offer": serialize_offer(offer),
        "cache_sync": sync_result,
    }


@router.get("/by-item/{item_id}")
async def get_offers_by_item(
    item_id: str,
    db_session: AsyncSession = Depends(get_offer_session_dependency),
    redis_client: Redis = Depends(get_offer_redis_dependency),
) -> dict[str, Any]:
    redis_error: str | None = None
    try:
        cached = await redis_client.get(offer_item_key(item_id))
        if cached:
            decoded = json.loads(cached)
            if isinstance(decoded, list):
                return {"item_id": item_id, "offers": decoded, "source": "redis"}
    except Exception as exc:  # noqa: BLE001
        redis_error = str(exc)

    offers = (
        await db_session.execute(
            select(Offer)
            .where(
                Offer.is_active.is_(True),
                or_(Offer.item_ids.is_(None), Offer.item_ids.contains([item_id])),
            )
            .order_by(Offer.created_at.desc())
        )
    ).scalars().all()
    payload = [serialize_offer(offer) for offer in offers]

    try:
        await redis_client.set(offer_item_key(item_id), json.dumps(payload))
    except Exception as exc:  # noqa: BLE001
        redis_error = str(exc)

    response: dict[str, Any] = {"item_id": item_id, "offers": payload, "source": "database"}
    if redis_error:
        response["warning"] = f"Redis unavailable while reading offers cache: {redis_error}"
    return response
