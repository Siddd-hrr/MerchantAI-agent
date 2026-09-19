from __future__ import annotations

import json

from redis.asyncio import Redis

from shared.config import get_settings
from shared.redis_client import get_redis_client


class InvoiceStore:
    def __init__(self, redis_client: Redis | None = None) -> None:
        self._settings = get_settings()
        self._redis = redis_client or get_redis_client()

    async def store_invoice(self, invoice_id: str, invoice_payload: dict[str, object]) -> None:
        await self._redis.set(
            f"invoice:{invoice_id}",
            json.dumps(invoice_payload),
            ex=int(self._settings.reservation_ttl_seconds),
        )
