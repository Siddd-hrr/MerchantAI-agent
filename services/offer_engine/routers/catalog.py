from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import select

from services.offer_engine.availability_client import AvailabilityClient
from services.offer_engine.routers.common import get_availability_client_dependency, get_offer_redis_dependency
from shared.catalog_fields import is_expired
from shared.db import AsyncSessionLocal
from shared.models.item import Item

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _clean_catalog_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": str(payload.get("item_id", "")),
        "name": str(payload.get("name", "")),
        "brand": str(payload.get("brand", "")),
        "weight_per_unit": str(payload.get("weight_per_unit", "")),
        "expiry_date": str(payload.get("expiry_date", "")),
        "price_paise": int(payload.get("price_paise", 0)),
        "available_qty": int(payload.get("available_qty", 0)),
        "is_active": bool(payload.get("is_active", True)),
    }


async def _filter_true_available_items(
    items: list[dict[str, Any]],
    availability_client: AvailabilityClient,
) -> list[dict[str, Any]]:
    availability_by_item_id = await availability_client.get_true_available_qty_map(
        (str(item.get("item_id", "")) for item in items),
    )
    filtered_items: list[dict[str, Any]] = []
    for item in items:
        if is_expired(item.get("expiry_date")):
            continue
        item_id = str(item.get("item_id", ""))
        true_available_qty = int(availability_by_item_id.get(item_id, 0))
        if true_available_qty <= 0:
            continue
        item_with_true_qty = dict(item)
        item_with_true_qty["available_qty"] = true_available_qty
        filtered_items.append(item_with_true_qty)
    return filtered_items


@router.get("/pickable-items")
async def get_pickable_items(
    redis_client: Redis = Depends(get_offer_redis_dependency),
    availability_client: AvailabilityClient = Depends(get_availability_client_dependency),
) -> dict[str, Any]:
    redis_error: str | None = None
    try:
        raw_index = await redis_client.get("catalog:index")
        if raw_index:
            index_payload = json.loads(raw_index)
            if isinstance(index_payload, list):
                items_from_index = {
                    str(item.get("item_id")): _clean_catalog_payload(item)
                    for item in index_payload
                    if item.get("item_id")
                }
                item_ids = list(items_from_index.keys())
                if item_ids:
                    redis_keys = [f"catalog:item:{item_id}" for item_id in item_ids]
                    cached_items = await redis_client.mget(redis_keys)
                    pickable_items: list[dict[str, Any]] = []

                    for item_id, cached_item in zip(item_ids, cached_items, strict=False):
                        if cached_item:
                            parsed_item = json.loads(cached_item)
                            pickable_items.append(_clean_catalog_payload(parsed_item))
                        else:
                            pickable_items.append(items_from_index[item_id])

                    active_items = [item for item in pickable_items if item["is_active"]]
                    true_available_items = await _filter_true_available_items(active_items, availability_client)
                    return {"source": "redis", "items": true_available_items}
    except Exception as exc:  # noqa: BLE001
        redis_error = str(exc)

    async with AsyncSessionLocal() as db_session:
        rows = (
            await db_session.execute(
                select(Item).where(Item.is_active.is_(True)).order_by(Item.name.asc(), Item.brand.asc())
            )
        ).scalars().all()
        items = [
            {
                "item_id": str(item.id),
                "name": item.name,
                "brand": item.brand,
                "weight_per_unit": item.weight_per_unit,
                "expiry_date": item.expiry_date.isoformat(),
                "price_paise": int(item.price_paise),
                "available_qty": int(item.quantity_available),
                "is_active": bool(item.is_active),
            }
            for item in rows
        ]

    true_available_items = await _filter_true_available_items(items, availability_client)
    response: dict[str, Any] = {"source": "database_fallback", "items": true_available_items}
    if redis_error:
        response["warning"] = f"Redis unavailable while reading catalog cache: {redis_error}"
    return response
