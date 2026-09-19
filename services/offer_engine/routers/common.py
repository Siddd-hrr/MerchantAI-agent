from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from services.offer_engine.availability_client import AvailabilityClient
from services.offer_engine.db import OfferSessionLocal
from services.offer_engine.redis_sync import serialize_offer
from shared.config import get_settings
from shared.models.offer import Offer
from shared.redis_client import close_redis_client, get_redis_client


async def get_offer_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    async with OfferSessionLocal() as session:
        yield session


async def get_offer_redis_dependency() -> AsyncGenerator[Redis, None]:
    settings = get_settings()
    redis_client = get_redis_client(settings.offer_redis_url_resolved)
    try:
        yield redis_client
    finally:
        await close_redis_client(redis_client)


def get_availability_client_dependency() -> AvailabilityClient:
    return AvailabilityClient()


def build_offer_create_response(offer: Offer, sync_result: dict[str, Any]) -> dict[str, Any] | JSONResponse:
    payload = {
        "status": "ok",
        "offer": serialize_offer(offer),
        "redis_sync": sync_result,
    }
    if sync_result.get("success", False):
        return payload

    payload["status"] = "partial_success"
    payload["message"] = "Offer saved in database but Redis sync had failures."
    return JSONResponse(status_code=207, content=payload)
