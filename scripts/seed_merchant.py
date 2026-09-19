from __future__ import annotations

import asyncio

from sqlalchemy import select

from services.auth_service.merchant_cache import sync_merchant_cache
from services.auth_service.password import hash_password
from shared.crypto import encrypt_secret
from shared.db import AsyncSessionLocal
from shared.models.merchant import Merchant
from shared.redis_client import close_redis_client, get_redis_client

DEMO_EMAIL = "demo@acmemart.test"
DEMO_PASSWORD = "demo-pass-123"
DEMO_ISSUERS = ["issuer-a"]
DEMO_RAZORPAY_KEY_ID = "rzp_test_demo"
DEMO_RAZORPAY_SECRET = "secret_demo"


async def seed_demo_merchant() -> Merchant:
    async with AsyncSessionLocal() as session:
        merchant = (
            await session.execute(select(Merchant).where(Merchant.email == DEMO_EMAIL))
        ).scalar_one_or_none()

        if merchant is None:
            merchant = Merchant(email=DEMO_EMAIL)
            session.add(merchant)

        merchant.password_hash = hash_password(DEMO_PASSWORD)
        merchant.display_name = "Acme Mart Demo"
        merchant.trusted_issuers = DEMO_ISSUERS
        merchant.razorpay_key_id = DEMO_RAZORPAY_KEY_ID
        merchant.razorpay_key_secret_encrypted = encrypt_secret(DEMO_RAZORPAY_SECRET)
        merchant.is_active = True

        await session.commit()
        await session.refresh(merchant)
        return merchant


async def main() -> None:
    merchant = await seed_demo_merchant()
    redis_client = get_redis_client()
    try:
        await sync_merchant_cache(redis_client, merchant)
    finally:
        await close_redis_client(redis_client)

    print(f"Seeded merchant {merchant.email} ({merchant.id})")


if __name__ == "__main__":
    asyncio.run(main())
