from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from services.auth_service.main import app
import services.auth_service.router as auth_router
from services.auth_service.password import hash_password
from shared.crypto import encrypt_secret
from shared.models.merchant import Merchant


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)


class FakeSession:
    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None


@pytest.mark.asyncio
async def test_signup_login_profile_and_cache_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    fake_redis = FakeRedis()
    fake_session = FakeSession()
    merchants_by_email: dict[str, Merchant] = {}
    merchants_by_id: dict[str, Merchant] = {}

    async def fake_db_dependency():
        yield fake_session

    async def fake_redis_dependency():
        yield fake_redis

    async def fake_get_by_email(_session, email: str):
        return merchants_by_email.get(email.lower())

    async def fake_get_by_id(_session, merchant_id):
        return merchants_by_id.get(str(merchant_id))

    async def fake_create(_session, payload):
        merchant = Merchant(
            id=uuid4(),
            email=payload.email.lower(),
            password_hash=hash_password(payload.password),
            display_name=payload.display_name,
            trusted_issuers=payload.resolved_trusted_issuers(),
            razorpay_key_id=payload.razorpay_key_id,
            razorpay_key_secret_encrypted=encrypt_secret(payload.razorpay_key_secret)
            if payload.razorpay_key_secret
            else None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        merchants_by_email[merchant.email] = merchant
        merchants_by_id[str(merchant.id)] = merchant
        return merchant

    async def fake_update(_session, merchant: Merchant, payload):
        if payload.display_name is not None:
            merchant.display_name = payload.display_name
        resolved_trusted_issuers = payload.resolved_trusted_issuers()
        if resolved_trusted_issuers is not None:
            merchant.trusted_issuers = resolved_trusted_issuers
        if payload.razorpay_key_id is not None:
            merchant.razorpay_key_id = payload.razorpay_key_id
        if payload.razorpay_key_secret is not None:
            merchant.razorpay_key_secret_encrypted = encrypt_secret(payload.razorpay_key_secret)
        merchant.updated_at = datetime.now(UTC)
        return merchant

    monkeypatch.setattr(auth_router, "_get_merchant_by_email", fake_get_by_email)
    monkeypatch.setattr(auth_router, "_get_merchant_by_id", fake_get_by_id)
    monkeypatch.setattr(auth_router, "_create_merchant", fake_create)
    monkeypatch.setattr(auth_router, "_apply_profile_update", fake_update)
    app.dependency_overrides[auth_router.get_db_dependency] = fake_db_dependency
    app.dependency_overrides[auth_router.get_redis_dependency] = fake_redis_dependency

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        signup_response = await client.post(
            "/auth/signup",
            json={
                "email": "demo@acmemart.test",
                "password": "demo-pass-123",
                "display_name": "Acme Mart",
                "trusted_issuers": ["issuer-a"],
                "razorpay_key_id": "rzp_test_demo",
                "razorpay_key_secret": "secret_demo",
            },
        )
        assert signup_response.status_code == 201
        signup_body = signup_response.json()
        assert signup_body["token_type"] == "bearer"
        assert "razorpay_key_secret" not in json.dumps(signup_body)
        assert "secret_demo" not in json.dumps(signup_body)

        merchant_id = signup_body["profile"]["id"]
        creds_cache_key = f"merchant:{merchant_id}:razorpay_creds"
        issuers_cache_key = f"merchant:{merchant_id}:trusted_issuers"
        assert creds_cache_key in fake_redis.store
        assert issuers_cache_key in fake_redis.store
        assert json.loads(fake_redis.store[creds_cache_key]) == {
            "key_id": "rzp_test_demo",
            "key_secret_encrypted": merchants_by_id[merchant_id].razorpay_key_secret_encrypted,
        }
        assert "secret_demo" not in fake_redis.store[creds_cache_key]
        assert json.loads(fake_redis.store[issuers_cache_key]) == ["issuer-a"]

        alias_signup_response = await client.post(
            "/auth/signup",
            json={
                "email": "alias@acmemart.test",
                "password": "demo-pass-456",
                "display_name": "Alias Mart",
                "trusted_mandate_issuers": ["issuer-z"],
            },
        )
        assert alias_signup_response.status_code == 201
        alias_body = alias_signup_response.json()
        assert alias_body["profile"]["trusted_issuers"] == ["issuer-z"]

        login_response = await client.post(
            "/auth/login",
            json={"email": "demo@acmemart.test", "password": "demo-pass-123"},
        )
        assert login_response.status_code == 200
        login_body = login_response.json()
        token = login_body["access_token"]

        profile_response = await client.get(
            "/auth/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert profile_response.status_code == 200
        profile_body = profile_response.json()
        assert profile_body["email"] == "demo@acmemart.test"
        assert "razorpay_key_secret" not in profile_body

        update_response = await client.put(
            "/auth/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "display_name": "Acme Mart Updated",
                "trusted_issuers": ["issuer-a", "issuer-b"],
            },
        )
        assert update_response.status_code == 200
        updated_profile = update_response.json()
        assert updated_profile["display_name"] == "Acme Mart Updated"
        assert updated_profile["trusted_issuers"] == ["issuer-a", "issuer-b"]
        assert json.loads(fake_redis.store[issuers_cache_key]) == ["issuer-a", "issuer-b"]

        alias_update_response = await client.put(
            "/auth/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"trusted_mandate_issuers": ["issuer-c"]},
        )
        assert alias_update_response.status_code == 200
        alias_profile = alias_update_response.json()
        assert alias_profile["trusted_issuers"] == ["issuer-c"]
        assert json.loads(fake_redis.store[issuers_cache_key]) == ["issuer-c"]

        wipe_response = await client.put(
            "/auth/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"trusted_issuers": []},
        )
        assert wipe_response.status_code == 422
        assert json.loads(fake_redis.store[issuers_cache_key]) == ["issuer-c"]

    app.dependency_overrides.clear()
