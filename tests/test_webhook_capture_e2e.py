"""Mock E2E for Razorpay → :8008 ingress → async_worker verify-enqueue ACK contract."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.async_worker.webhook_router import router as webhook_router
from services.payment_log_service.ingress_forwarder import ForwardResult
from services.payment_log_service.router import router as payment_log_router


class _FakeProducer:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bytes]] = []
        self.fail = False

    async def send_and_wait(self, topic: str, value: bytes) -> None:
        if self.fail:
            raise RuntimeError("kafka down")
        self.messages.append((topic, value))


@pytest.mark.asyncio
async def test_ingress_relays_worker_status(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_forward(*, worker_url: str, raw_body: bytes, headers: dict[str, str]) -> ForwardResult:
        calls.append({"worker_url": worker_url, "raw_body": raw_body, "headers": headers})
        return ForwardResult(status_code=200, body=b'{"status":"enqueued"}', media_type="application/json")

    monkeypatch.setattr(
        "services.payment_log_service.router.forward_to_worker",
        fake_forward,
    )
    monkeypatch.setattr(
        "services.payment_log_service.router.get_settings",
        lambda: type("S", (), {"worker_url": "http://worker-test"})(),
    )

    app = FastAPI()
    app.include_router(payment_log_router)
    transport = ASGITransport(app=app)
    body = b'{"event":"payment.captured"}'
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.post(
            "/webhook/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": "sig", "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "enqueued"
    assert calls[0]["worker_url"] == "http://worker-test"
    assert calls[0]["raw_body"] == body
    assert calls[0]["headers"]["x-razorpay-signature"] == "sig" or calls[0]["headers"].get(
        "X-Razorpay-Signature"
    ) == "sig"


@pytest.mark.asyncio
async def test_verify_enqueue_rejects_bad_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    producer = _FakeProducer()
    monkeypatch.setattr(
        "services.async_worker.webhook_router.get_settings",
        lambda: type("S", (), {"razorpay_webhook_secret": "whsec_test"})(),
    )
    app = FastAPI()
    app.state.kafka_producer = producer  # type: ignore[attr-defined]
    app.include_router(webhook_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.post(
            "/internal/razorpay-webhook/verify-enqueue",
            content=b'{"event":"payment.captured"}',
            headers={"X-Razorpay-Signature": "nope"},
        )
    assert response.status_code == 401
    assert producer.messages == []


@pytest.mark.asyncio
async def test_verify_enqueue_persists_then_acks(monkeypatch: pytest.MonkeyPatch) -> None:
    producer = _FakeProducer()
    secret = "whsec_test"
    body = b'{"event":"payment.captured","payload":{}}'
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    monkeypatch.setattr(
        "services.async_worker.webhook_router.get_settings",
        lambda: type("S", (), {"razorpay_webhook_secret": secret})(),
    )
    app = FastAPI()
    app.state.kafka_producer = producer  # type: ignore[attr-defined]
    app.include_router(webhook_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.post(
            "/internal/razorpay-webhook/verify-enqueue",
            content=body,
            headers={"X-Razorpay-Signature": signature},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "enqueued"
    assert len(producer.messages) == 1
    topic, payload = producer.messages[0]
    assert topic == "webhook-queue"
    assert json.loads(payload.decode())["raw_body"] == body.decode()


@pytest.mark.asyncio
async def test_verify_enqueue_persist_fail_returns_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    producer = _FakeProducer()
    producer.fail = True
    secret = "whsec_test"
    body = b'{"event":"payment.captured"}'
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    monkeypatch.setattr(
        "services.async_worker.webhook_router.get_settings",
        lambda: type("S", (), {"razorpay_webhook_secret": secret})(),
    )
    app = FastAPI()
    app.state.kafka_producer = producer  # type: ignore[attr-defined]
    app.include_router(webhook_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.post(
            "/internal/razorpay-webhook/verify-enqueue",
            content=body,
            headers={"X-Razorpay-Signature": signature},
        )
    assert response.status_code == 500
