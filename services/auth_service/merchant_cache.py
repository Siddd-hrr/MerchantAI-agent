from __future__ import annotations

import json

from redis.asyncio import Redis

from shared.models.merchant import Merchant


async def sync_merchant_cache(redis: Redis, merchant: Merchant) -> None:
    """Cache encrypted credentials only — never plaintext secrets."""
    await redis.set(
        f"merchant:{merchant.id}:razorpay_creds",
        json.dumps(
            {
                "key_id": merchant.razorpay_key_id or "",
                "key_secret_encrypted": merchant.razorpay_key_secret_encrypted or "",
            }
        ),
    )
    await redis.set(
        f"merchant:{merchant.id}:trusted_issuers",
        json.dumps(merchant.trusted_issuers or []),
    )
