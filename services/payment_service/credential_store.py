from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.auth_service.merchant_cache import sync_merchant_cache
from shared.crypto import decrypt_secret
from shared.models.merchant import Merchant
from shared.redis_client import get_redis_client


@dataclass(slots=True)
class MerchantCredentials:
    merchant_id: str
    key_id: str
    key_secret: str


class MerchantCredentialStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client or get_redis_client()

    async def _from_cache(self, merchant_id: str) -> MerchantCredentials | None:
        raw = await self._redis.get(f"merchant:{merchant_id}:razorpay_creds")
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        key_id = str(parsed.get("key_id", "")).strip()
        encrypted = str(parsed.get("key_secret_encrypted", "")).strip()
        if not key_id or not encrypted:
            return None
        try:
            key_secret = decrypt_secret(encrypted)
        except Exception:
            return None
        return MerchantCredentials(merchant_id=merchant_id, key_id=key_id, key_secret=key_secret)

    async def _from_db(self, merchant_id: str) -> MerchantCredentials | None:
        try:
            merchant_uuid = UUID(merchant_id)
        except ValueError:
            return None

        async with self._session_factory() as db_session:
            merchant = (
                await db_session.execute(select(Merchant).where(Merchant.id == merchant_uuid))
            ).scalar_one_or_none()
        if merchant is None:
            return None
        if not merchant.razorpay_key_id or not merchant.razorpay_key_secret_encrypted:
            return None
        await sync_merchant_cache(self._redis, merchant)
        try:
            key_secret = decrypt_secret(merchant.razorpay_key_secret_encrypted)
        except Exception:
            return None
        return MerchantCredentials(
            merchant_id=merchant_id,
            key_id=merchant.razorpay_key_id,
            key_secret=key_secret,
        )

    async def get_credentials(self, merchant_id: str) -> MerchantCredentials | None:
        cached = await self._from_cache(merchant_id)
        if cached is not None:
            return cached
        return await self._from_db(merchant_id)
