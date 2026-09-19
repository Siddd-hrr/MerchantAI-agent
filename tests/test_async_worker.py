from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from services.async_worker import main as worker_main
from services.async_worker import mandate_verifier
from shared.schemas.conversation import ConverseResponse


class FakeRedis:
    def __init__(self, *, existing_seen: bool = False, seed: dict[str, str] | None = None) -> None:
        self.existing_seen = existing_seen
        self.seed = dict(seed or {})
        self.set_calls: list[tuple[str, str, int | None]] = []

    async def get(self, key: str) -> str | None:
        if key in self.seed:
            return self.seed[key]
        if self.existing_seen and key.startswith("mandate:seen:"):
            return "1"
        return None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.seed[key] = value
        self.set_calls.append((key, value, ex))


def _encode_mandate(payload: dict[str, object]) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


@pytest.mark.asyncio
async def test_invalid_mandate_raises_exact_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_write_failure(**_kwargs) -> None:
        return None

    monkeypatch.setattr(mandate_verifier, "_write_mandate_failure_audit", fake_write_failure)

    with pytest.raises(mandate_verifier.MandateVerificationError) as exc_info:
        await mandate_verifier.verify_mandate(
            session_id="s-invalid",
            consumer_agent_id="consumer-1",
            human_sign_mandate="not-valid-base64",
        )

    assert exc_info.value.error_payload == {
        "error": {
            "code": "MANDATE_INVALID",
            "message": "Please include a cryptographic signature issued by a trusted issuer to establish contact with the Merchant-AI agent.",
        }
    }


@pytest.mark.asyncio
async def test_replay_mandate_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    mandate = _encode_mandate(
        {
            "issuer": "issuer-a",
            "subject": "agent-1",
            "issued_at": now_epoch,
            "signature": "same-signature",
        }
    )
    fake_redis = FakeRedis(existing_seen=True)

    async def fake_write_failure(**_kwargs) -> None:
        return None

    monkeypatch.setattr(mandate_verifier, "get_settings", lambda: SimpleNamespace(
        trusted_mandate_issuers_list=["issuer-a"],
        mandate_max_age_seconds=300,
    ))
    monkeypatch.setattr(mandate_verifier, "get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(mandate_verifier, "_write_mandate_failure_audit", fake_write_failure)

    with pytest.raises(mandate_verifier.MandateVerificationError):
        await mandate_verifier.verify_mandate(
            session_id="s-replay",
            consumer_agent_id="consumer-1",
            human_sign_mandate=mandate,
        )

    assert fake_redis.set_calls == []


@pytest.mark.asyncio
async def test_valid_mandate_marks_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    mandate = _encode_mandate(
        {
            "issuer": "issuer-a",
            "subject": "agent-1",
            "issued_at": now_epoch,
            "signature": "unique-signature",
        }
    )
    fake_redis = FakeRedis(existing_seen=False)

    monkeypatch.setattr(mandate_verifier, "get_settings", lambda: SimpleNamespace(
        trusted_mandate_issuers_list=["issuer-a"],
        mandate_max_age_seconds=300,
    ))
    monkeypatch.setattr(mandate_verifier, "get_redis_client", lambda: fake_redis)

    claims = await mandate_verifier.verify_mandate(
        session_id="s-valid",
        consumer_agent_id="consumer-1",
        human_sign_mandate=mandate,
    )

    assert claims.issuer == "issuer-a"
    assert claims.subject == "agent-1"
    assert fake_redis.set_calls and fake_redis.set_calls[0][0].startswith("mandate:seen:")
    assert fake_redis.set_calls[0][2] == 300


@pytest.mark.asyncio
async def test_merchant_trusted_issuers_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    mandate = _encode_mandate(
        {
            "issuer": "merchant-issuer",
            "subject": "agent-1",
            "issued_at": now_epoch,
            "signature": "merchant-signature",
        }
    )
    fake_redis = FakeRedis(
        existing_seen=False,
        seed={"merchant:merchant-123:trusted_issuers": json.dumps(["merchant-issuer"])},
    )

    monkeypatch.setattr(
        mandate_verifier,
        "get_settings",
        lambda: SimpleNamespace(
            trusted_mandate_issuers_list=["env-issuer"],
            mandate_max_age_seconds=300,
        ),
    )
    monkeypatch.setattr(mandate_verifier, "get_redis_client", lambda: fake_redis)

    claims = await mandate_verifier.verify_mandate(
        session_id="s-merchant-override",
        consumer_agent_id="consumer-1",
        human_sign_mandate=mandate,
        merchant_id="merchant-123",
    )

    assert claims.issuer == "merchant-issuer"
    assert fake_redis.set_calls and fake_redis.set_calls[0][0].startswith("mandate:seen:")


@pytest.mark.asyncio
async def test_worker_returns_failed_without_forward_on_mandate_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def always_fail_verify(**_kwargs):
        raise mandate_verifier.MandateVerificationError()

    async def should_not_forward(**_kwargs):
        raise AssertionError("forward_to_agent should not be called for invalid mandates")

    monkeypatch.setattr(worker_main, "verify_mandate", always_fail_verify)
    monkeypatch.setattr(worker_main, "forward_to_agent", should_not_forward)

    transport = httpx.ASGITransport(app=worker_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/v1/worker/converse",
            json={
                "consumer_agent_id": "consumer-1",
                "session_id": "s-worker-fail",
                "message": "hello",
                "human_sign_mandate": "invalid",
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "FAILED"
    assert body["error"] == {
        "code": "MANDATE_INVALID",
        "message": "Please include a cryptographic signature issued by a trusted issuer to establish contact with the Merchant-AI agent.",
    }

    parsed = ConverseResponse.model_validate(body)
    assert parsed.status == "FAILED"
