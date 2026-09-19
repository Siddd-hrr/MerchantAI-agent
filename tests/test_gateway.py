from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.gateway.routers import converse
from shared.schemas.conversation import ConverseRequest


@pytest.mark.asyncio
async def test_gateway_converse_forwards_to_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    converse._rate_limit_buckets.clear()
    converse.settings = SimpleNamespace(worker_url="http://worker.internal", rate_limit_per_minute=60)

    seen = {"url": "", "json": None}

    class FakeResponse:
        def __init__(self) -> None:
            self._payload = {
                "session_id": "session-1",
                "status": "AWAITING_FIELDS",
                "reply": "Need address",
                "missing_fields": ["address"],
                "catalog_suggestions": [],
                "invoice": None,
                "error": None,
            }

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, json: dict):
            seen["url"] = url
            seen["json"] = json
            return FakeResponse()

    monkeypatch.setattr(converse.httpx, "AsyncClient", FakeAsyncClient)

    response = await converse.converse(
        ConverseRequest(
            consumer_agent_id="consumer-1",
            merchant_id="merchant-1",
            session_id="session-1",
            message="Order milk",
            human_sign_mandate="abc",
        )
    )

    assert seen["url"] == "http://worker.internal/v1/worker/converse"
    assert seen["json"]["consumer_agent_id"] == "consumer-1"
    assert seen["json"]["merchant_id"] == "merchant-1"
    assert response.status == "AWAITING_FIELDS"


@pytest.mark.asyncio
async def test_gateway_rate_limit_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    converse._rate_limit_buckets.clear()
    converse.settings = SimpleNamespace(worker_url="http://worker.internal", rate_limit_per_minute=1)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "session_id": "session-1",
                "status": "AWAITING_FIELDS",
                "reply": "Need address",
                "missing_fields": ["address"],
                "catalog_suggestions": [],
                "invoice": None,
                "error": None,
            }

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(converse.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient())

    first = await converse.converse(
        ConverseRequest(
            consumer_agent_id="consumer-1",
            session_id="session-1",
            message="Order milk",
            human_sign_mandate="abc",
        )
    )
    second = await converse.converse(
        ConverseRequest(
            consumer_agent_id="consumer-1",
            session_id="session-1",
            message="Order milk",
            human_sign_mandate="abc",
        )
    )

    assert first.status == "AWAITING_FIELDS"
    assert second.status == "FAILED"
    assert second.error is not None
    assert second.error.code == "RATE_LIMITED"
