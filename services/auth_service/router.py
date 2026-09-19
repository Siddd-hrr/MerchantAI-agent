from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_service.jwt_tokens import create_access_token, decode_token
from services.auth_service.merchant_cache import sync_merchant_cache
from services.auth_service.password import hash_password, verify_password
from services.auth_service.schemas import (
    AuthResponse,
    MerchantLoginRequest,
    MerchantProfileResponse,
    MerchantProfileUpdateRequest,
    MerchantSignupRequest,
)
from shared.crypto import encrypt_secret
from shared.db import AsyncSessionLocal
from shared.models.merchant import Merchant
from shared.redis_client import close_redis_client, get_redis_client

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)


async def get_db_dependency() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_redis_dependency() -> AsyncGenerator[Redis, None]:
    redis_client = get_redis_client()
    try:
        yield redis_client
    finally:
        await close_redis_client(redis_client)


async def _get_merchant_by_email(db_session: AsyncSession, email: str) -> Merchant | None:
    result = await db_session.execute(select(Merchant).where(Merchant.email == email.lower()))
    return result.scalar_one_or_none()


async def _get_merchant_by_id(db_session: AsyncSession, merchant_id: UUID) -> Merchant | None:
    result = await db_session.execute(select(Merchant).where(Merchant.id == merchant_id))
    return result.scalar_one_or_none()


def _profile_from_merchant(merchant: Merchant) -> MerchantProfileResponse:
    return MerchantProfileResponse(
        id=merchant.id,
        email=merchant.email,
        display_name=merchant.display_name,
        trusted_issuers=merchant.trusted_issuers or [],
        razorpay_key_id=merchant.razorpay_key_id,
        is_active=merchant.is_active,
        created_at=merchant.created_at,
        updated_at=merchant.updated_at,
    )


async def _create_merchant(db_session: AsyncSession, payload: MerchantSignupRequest) -> Merchant:
    merchant = Merchant(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        display_name=payload.resolved_display_name(),
        trusted_issuers=payload.resolved_trusted_issuers(),
        razorpay_key_id=payload.razorpay_key_id,
        razorpay_key_secret_encrypted=encrypt_secret(payload.razorpay_key_secret)
        if payload.razorpay_key_secret
        else None,
    )
    db_session.add(merchant)
    await db_session.commit()
    await db_session.refresh(merchant)
    return merchant


async def _apply_profile_update(
    db_session: AsyncSession, merchant: Merchant, payload: MerchantProfileUpdateRequest
) -> Merchant:
    if payload.display_name is not None:
        merchant.display_name = payload.display_name
    resolved_trusted_issuers = payload.resolved_trusted_issuers()
    if resolved_trusted_issuers is not None:
        merchant.trusted_issuers = resolved_trusted_issuers
    if payload.razorpay_key_id is not None:
        merchant.razorpay_key_id = payload.razorpay_key_id
    if payload.razorpay_key_secret is not None:
        merchant.razorpay_key_secret_encrypted = encrypt_secret(payload.razorpay_key_secret)
    if payload.password is not None:
        merchant.password_hash = hash_password(payload.password)
    merchant.updated_at = datetime.now(UTC)
    await db_session.commit()
    await db_session.refresh(merchant)
    return merchant


async def get_current_merchant(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db_session: AsyncSession = Depends(get_db_dependency),
) -> Merchant:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")

    try:
        payload = decode_token(credentials.credentials)
        merchant_id = UUID(str(payload["sub"]))
    except (ValueError, KeyError, jwt.PyJWTError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token.") from None

    merchant = await _get_merchant_by_id(db_session, merchant_id)
    if merchant is None or not merchant.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Merchant is not authorized.")
    return merchant


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: MerchantSignupRequest,
    db_session: AsyncSession = Depends(get_db_dependency),
    redis_client: Redis = Depends(get_redis_dependency),
) -> AuthResponse:
    existing = await _get_merchant_by_email(db_session, payload.email)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Merchant already exists.")

    merchant = await _create_merchant(db_session, payload)
    await sync_merchant_cache(redis_client, merchant)
    access_token = create_access_token(str(merchant.id), merchant.email)
    return AuthResponse(access_token=access_token, profile=_profile_from_merchant(merchant))


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: MerchantLoginRequest,
    db_session: AsyncSession = Depends(get_db_dependency),
    redis_client: Redis = Depends(get_redis_dependency),
) -> AuthResponse:
    merchant = await _get_merchant_by_email(db_session, payload.email)
    if merchant is None or not merchant.is_active or not verify_password(payload.password, merchant.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    await sync_merchant_cache(redis_client, merchant)
    access_token = create_access_token(str(merchant.id), merchant.email)
    return AuthResponse(access_token=access_token, profile=_profile_from_merchant(merchant))


@router.get("/profile", response_model=MerchantProfileResponse)
async def get_profile(current_merchant: Merchant = Depends(get_current_merchant)) -> MerchantProfileResponse:
    return _profile_from_merchant(current_merchant)


@router.put("/profile", response_model=MerchantProfileResponse)
async def update_profile(
    payload: MerchantProfileUpdateRequest,
    current_merchant: Merchant = Depends(get_current_merchant),
    db_session: AsyncSession = Depends(get_db_dependency),
    redis_client: Redis = Depends(get_redis_dependency),
) -> MerchantProfileResponse:
    updated = await _apply_profile_update(db_session, current_merchant, payload)
    await sync_merchant_cache(redis_client, updated)
    return _profile_from_merchant(updated)
