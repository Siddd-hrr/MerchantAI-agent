from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from types import SimpleNamespace

from services.payment_service.credential_store import MerchantCredentials
import services.payment_service.router as payment_router
import services.payment_service.razorpay_client as razorpay_client
import shared.config as shared_config
from services.payment_service.router import build_router


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.set_calls.append((key, value, ex))

    async def delete(self, key: str) -> int:
        existed = 1 if key in self.store else 0
        self.store.pop(key, None)
        return existed


class FakeCredentialStore:
    def __init__(self, credentials: MerchantCredentials | None) -> None:
        self._credentials = credentials

    async def get_credentials(self, merchant_id: str) -> MerchantCredentials | None:
        _ = merchant_id
        return self._credentials


def _build_test_app(redis_client: FakeRedis, credential_store: FakeCredentialStore) -> FastAPI:
    app = FastAPI()
    app.include_router(build_router(credential_store, redis_client))
    return app


@pytest.mark.asyncio
async def test_payment_create_and_cancel_link_fake_mode() -> None:
    decrypted_secret = "rzp_test_demo_secret_plaintext"
    fake_redis = FakeRedis()
    fake_credentials = MerchantCredentials(
        merchant_id="merchant-1",
        key_id="rzp_test_demo",
        key_secret=decrypted_secret,
    )
    app = _build_test_app(fake_redis, FakeCredentialStore(fake_credentials))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        create_response = await client.post(
            "/payment/create-link",
            json={"merchant_id": "merchant-1", "invoice_id": "invoice-1", "amount_paise": 12345},
        )
        cancel_response = await client.post(
            "/payment/cancel-link",
            json={"merchant_id": "merchant-1", "invoice_id": "invoice-1"},
        )

    create_body = create_response.json()
    cancel_body = cancel_response.json()

    assert create_response.status_code == 200
    assert create_body["success"] is True
    assert create_body["payment_link_url"] == "https://rzp.io/i/fake-invoice-1"
    assert decrypted_secret not in create_response.text

    assert fake_redis.set_calls == [("payment_link:invoice-1", "plink_fake_invoice-1", 600)]
    assert cancel_response.status_code == 200
    assert cancel_body["success"] is True
    assert cancel_body["invoice_id"] == "invoice-1"
    assert cancel_body["cancelled"] is True
    assert cancel_body["error"] is None
    assert decrypted_secret not in cancel_response.text
    assert await fake_redis.get("payment_link:invoice-1") is None


@pytest.mark.asyncio
async def test_payment_create_link_accepts_phone_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    class _SpyClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def create_link(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            return SimpleNamespace(payment_link_id="plink_1", payment_link_url="https://rzp.io/i/t-1")

    spy = _SpyClient()
    monkeypatch.setattr(payment_router, "get_razorpay_client", lambda _credentials: spy)
    monkeypatch.setattr(shared_config, "get_settings", lambda: SimpleNamespace(payment_link_ttl_seconds=300, razorpay_mode="test"))

    fake_redis = FakeRedis()
    fake_credentials = MerchantCredentials(
        merchant_id="merchant-1",
        key_id="rzp_test_abcd",
        key_secret="rzp_test_secret",
    )
    app = _build_test_app(fake_redis, FakeCredentialStore(fake_credentials))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/payment/create-link",
            json={
                "merchant_id": "merchant-1",
                "session_id": "sess-1",
                "invoice_id": "invoice-2",
                "amount_paise": 1200,
                "customer_name": "Priya",
                "phone": "+919999888877",
                "description": "Invoice invoice-2 payment",
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert spy.calls == [
        {
            "merchant_id": "merchant-1",
            "invoice_id": "invoice-2",
            "session_id": "sess-1",
            "amount_paise": 1200,
            "customer_name": "Priya",
            "customer_phone": "+919999888877",
            "description": "Invoice invoice-2 payment",
        }
    ]


@pytest.mark.asyncio
async def test_payment_create_link_test_mode_fails_closed_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shared_config, "get_settings", lambda: SimpleNamespace(payment_link_ttl_seconds=300, razorpay_mode="test"))
    monkeypatch.setattr(razorpay_client, "get_settings", lambda: SimpleNamespace(razorpay_mode="test"))
    app = _build_test_app(FakeRedis(), FakeCredentialStore(credentials=None))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/payment/create-link",
            json={"merchant_id": "merchant-1", "invoice_id": "invoice-3", "amount_paise": 999},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False
    assert body["error"]["code"] == "RAZORPAY_CREDENTIALS_MISSING"
    assert body["payment_link_url"] is None
