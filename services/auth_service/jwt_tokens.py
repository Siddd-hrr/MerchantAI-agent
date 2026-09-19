from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from shared.config import get_settings

ALGORITHM = "HS256"


def _get_jwt_secret() -> str:
    settings = get_settings()
    return settings.jwt_secret or "dev-jwt-secret-change-me-please-32"


def create_access_token(merchant_id: str, email: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": merchant_id,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(token, _get_jwt_secret(), algorithms=[ALGORITHM])
    if "sub" not in payload:
        raise jwt.InvalidTokenError("Missing token subject.")
    return payload
