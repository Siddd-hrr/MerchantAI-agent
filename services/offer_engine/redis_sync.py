from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.models.offer import Offer


def offer_item_key(item_id: str) -> str:
    return f"offer:item:{item_id}"


def serialize_offer(offer: Offer) -> dict[str, Any]:
    return {
        "id": str(offer.id),
        "offer_type": offer.offer_type,
        "name": offer.name,
        "description": offer.description,
        "item_ids": offer.item_ids,
        "condition": offer.condition,
        "discount_type": offer.discount_type,
        "value": int(offer.value),
        "combo_with_item_ids": offer.combo_with_item_ids,
        "coupon_code": offer.coupon_code,
        "festival_name": offer.festival_name,
        "valid_from": offer.valid_from.isoformat() if isinstance(offer.valid_from, datetime) else None,
        "valid_to": offer.valid_to.isoformat() if isinstance(offer.valid_to, datetime) else None,
        "is_active": bool(offer.is_active),
        "created_at": offer.created_at.isoformat() if isinstance(offer.created_at, datetime) else None,
    }


async def _active_offers_for_item(db_session: AsyncSession, item_id: str) -> list[dict[str, Any]]:
    offers = (
        await db_session.execute(
            select(Offer)
            .where(
                Offer.is_active.is_(True),
                Offer.item_ids.is_not(None),
                Offer.item_ids.contains([item_id]),
            )
            .order_by(Offer.created_at.desc())
        )
    ).scalars().all()
    return [serialize_offer(offer) for offer in offers]


async def sync_offer_item_cache(
    redis_client: Redis,
    db_session: AsyncSession,
    item_ids: list[str] | None,
) -> dict[str, Any]:
    if not item_ids:
        return {"success": True, "synced_item_ids": [], "errors": []}

    settings = get_settings()
    unique_item_ids = sorted(set(item_ids))
    synced_item_ids: list[str] = []
    errors: list[dict[str, str]] = []

    for item_id in unique_item_ids:
        try:
            offers_for_item = await _active_offers_for_item(db_session, item_id)
            await redis_client.set(
                offer_item_key(item_id),
                json.dumps(offers_for_item),
                ex=settings.catalog_cache_ttl_seconds,
            )
            synced_item_ids.append(item_id)
        except Exception as exc:  # noqa: BLE001 - we need partial-success behavior here.
            errors.append({"item_id": item_id, "error": str(exc)})

    return {
        "success": not errors,
        "synced_item_ids": synced_item_ids,
        "errors": errors,
    }
