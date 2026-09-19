from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from services.auth_service.merchant_cache import sync_merchant_cache
from shared.config import get_settings
from shared.db import AsyncSessionLocal
from shared.models.audit_log import AuditLog
from shared.models.merchant import Merchant
from shared.redis_client import get_redis_client
from shared.schemas.mandate import MandateClaims

MANDATE_INVALID_ERROR = {
    "error": {
        "code": "MANDATE_INVALID",
        "message": "Please include a cryptographic signature issued by a trusted issuer to establish contact with the Merchant-AI agent.",
    }
}


class MandateVerificationError(Exception):
    def __init__(self) -> None:
        super().__init__(MANDATE_INVALID_ERROR["error"]["message"])
        self.error_payload = MANDATE_INVALID_ERROR


def _decode_mandate_token(token: str) -> dict[str, Any]:
    raw_token = token.strip()
    padding = "=" * (-len(raw_token) % 4)
    decoded = base64.b64decode(raw_token + padding)
    parsed = json.loads(decoded.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("mandate payload must be an object")
    return parsed


async def _write_mandate_failure_audit(
    *,
    session_id: str,
    detail: dict[str, Any],
) -> None:
    async with AsyncSessionLocal() as db_session:
        db_session.add(
            AuditLog(
                session_id=session_id,
                actor="async_worker",
                action="MANDATE_VERIFY_FAILED",
                detail=detail,
            )
        )
        await db_session.flush()
        redis = get_redis_client()
        await redis.xadd(
            "audit:stream",
            {
                "session_id": session_id,
                "actor": "async_worker",
                "action": "MANDATE_VERIFY_FAILED",
                "detail": json.dumps(detail),
            },
        )
        await db_session.commit()


def _parse_issuers(raw_issuers: str | None) -> list[str] | None:
    if not raw_issuers:
        return None
    try:
        parsed = json.loads(raw_issuers)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return [issuer.strip() for issuer in parsed if isinstance(issuer, str) and issuer.strip()]


async def _load_merchant_trusted_issuers(*, merchant_id: str, redis_key: str) -> list[str] | None:
    redis = get_redis_client()
    cached_issuers = _parse_issuers(await redis.get(redis_key))
    if cached_issuers is not None:
        return cached_issuers

    try:
        merchant_uuid = UUID(str(merchant_id))
    except ValueError:
        return None

    async with AsyncSessionLocal() as db_session:
        merchant = (
            await db_session.execute(select(Merchant).where(Merchant.id == merchant_uuid))
        ).scalar_one_or_none()
    if merchant is None:
        return None

    await sync_merchant_cache(redis, merchant)
    refreshed_issuers = _parse_issuers(await redis.get(redis_key))
    if refreshed_issuers is not None:
        return refreshed_issuers
    if merchant.trusted_issuers:
        return [issuer.strip() for issuer in merchant.trusted_issuers if issuer and issuer.strip()]
    return None


async def verify_mandate(
    *,
    session_id: str,
    consumer_agent_id: str,
    human_sign_mandate: str,
    merchant_id: str | None = None,
) -> MandateClaims:
    # MOCKED for hackathon Phase 1 — replace with real AP2/ACP mandate verification before production.
    settings = get_settings()
    redis = get_redis_client()
    try:
        trusted_issuers = settings.trusted_mandate_issuers_list
        if merchant_id:
            merchant_issuers = await _load_merchant_trusted_issuers(
                merchant_id=merchant_id,
                redis_key=f"merchant:{merchant_id}:trusted_issuers",
            )
            if merchant_issuers:
                trusted_issuers = merchant_issuers
            elif not settings.allow_global_trusted_issuers_fallback:
                raise ValueError("merchant trusted issuers are missing")

        claims = MandateClaims.model_validate(_decode_mandate_token(human_sign_mandate))
        if claims.issuer not in trusted_issuers:
            raise ValueError("issuer is not trusted")

        now_epoch = int(datetime.now(timezone.utc).timestamp())
        if claims.issued_at > now_epoch:
            raise ValueError("issued_at cannot be in the future")
        if now_epoch - claims.issued_at > settings.mandate_max_age_seconds:
            raise ValueError("mandate is too old")
        if not claims.signature.strip():
            raise ValueError("signature is empty")

        signature_hash = hashlib.sha256(claims.signature.encode("utf-8")).hexdigest()
        replay_key = f"mandate:seen:{signature_hash}"
        already_seen = await redis.get(replay_key)
        if already_seen:
            raise ValueError("replay detected")
        await redis.set(replay_key, "1", ex=300)
        return claims
    except Exception as exc:
        failure_detail = {
            "consumer_agent_id": consumer_agent_id,
            "reason": str(exc),
        }
        try:
            await _write_mandate_failure_audit(
                session_id=session_id,
                detail=failure_detail,
            )
        except Exception:
            pass
        raise MandateVerificationError() from exc
