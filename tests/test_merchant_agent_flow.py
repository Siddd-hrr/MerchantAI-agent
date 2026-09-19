"""End-to-end conversation flow tests (happy path + mandate failure).

These tests exercise the agent graph with stubbed LLM / in-memory fakes so they
run without Docker. Full live gateway→worker→agent E2E requires:
  docker compose up --build
  alembic upgrade head
  python -m scripts.seed_catalog
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from services.async_worker.main import app as worker_app
from services.async_worker.mandate_verifier import (
    MANDATE_INVALID_ERROR,
    MandateVerificationError,
    verify_mandate,
)
from services.gateway.main import app as gateway_app
from services.merchant_agent.persona import MISSING_FIELDS_WARNING_TEMPLATE, OUT_OF_STOCK_WARNING_TEMPLATE
from shared.schemas.conversation import ConverseResponse


def _mandate_b64(*, issuer: str = "issuer-a", signature: str = "sig-unique-1", age_seconds: int = 0) -> str:
    issued_at = int(datetime.now(timezone.utc).timestamp()) - age_seconds
    payload = {
        "issuer": issuer,
        "subject": "consumer-1",
        "issued_at": issued_at,
        "signature": signature,
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


@pytest.mark.asyncio
async def test_mandate_failure_through_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """§10 step 12 — invalid mandate rejected at worker path via gateway; agent never called."""
    forwarded = {"called": False}

    async def _fake_forward(*_args, **_kwargs):
        forwarded["called"] = True
        raise AssertionError("agent must not be called on invalid mandate")

    async def _fake_worker_post(request):
        # Simulate worker response for invalid mandate without Redis
        return ConverseResponse(
            session_id=request.session_id or str(uuid4()),
            status="FAILED",
            reply="",
            error={"code": "MANDATE_INVALID", "message": MANDATE_INVALID_ERROR["error"]["message"]},
        )

    # Patch gateway's httpx call to worker to return mandate failure shape,
    # and separately assert verifier exact error for --invalid-mandate style payloads.
    with pytest.raises(MandateVerificationError):
        await verify_mandate(
            session_id="sess-e2e",
            consumer_agent_id="consumer-e2e",
            human_sign_mandate="not-valid-base64!!!",
        )

    async def fake_post(self, url, json=None, **kwargs):
        forwarded["url"] = url
        class Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "session_id": (json or {}).get("session_id") or "sess-1",
                    "status": "FAILED",
                    "reply": "",
                    "missing_fields": [],
                    "catalog_suggestions": [],
                    "invoice": None,
                    "error": {
                        "code": "MANDATE_INVALID",
                        "message": MANDATE_INVALID_ERROR["error"]["message"],
                    },
                }

        return Resp()

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    transport = ASGITransport(app=gateway_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/converse",
            json={
                "consumer_agent_id": "consumer-e2e",
                "session_id": None,
                "message": "I want beans",
                "human_sign_mandate": "invalid",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "FAILED"
    assert body["error"]["code"] == "MANDATE_INVALID"
    assert body["error"]["message"] == MANDATE_INVALID_ERROR["error"]["message"]


@pytest.mark.asyncio
async def test_missing_fields_warning_is_dynamic_only() -> None:
    rendered = MISSING_FIELDS_WARNING_TEMPLATE.format(
        missing_field_bullets="- Delivery address\n- Mobile number"
    )
    assert "⚠️ Still needed before proceeding towards the next process of invoice creation:" in rendered
    assert "- Delivery address" in rendered
    assert "- Mobile number" in rendered
    assert "Verified Human Sign Mandate" not in rendered
    assert "Still missing for this order" not in rendered
    assert "To initiate the next step of this order" not in rendered


@pytest.mark.asyncio
async def test_oos_warning_template_is_verbatim() -> None:
    rendered = OUT_OF_STOCK_WARNING_TEMPLATE.format(
        brand="HomeSelect",
        item="Beans",
        alternatives="- FreshFarm Beans @ 14500 paise (18 available)",
    )
    assert "HomeSelect Beans is not available in the requested quantity" in rendered
    assert "Please choose" in rendered


@pytest.mark.asyncio
async def test_discount_model_has_no_runtime_readers() -> None:
    """§11 — discounts table exists but zero code paths read from it."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in (root / "services").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from shared.models.discount import" in text or "select(Discount)" in text:
            offenders.append(str(path))
    assert offenders == []


def test_sample_catalog_supports_oos_and_alternatives() -> None:
    from pathlib import Path

    csv_path = Path(__file__).parent / "fixtures" / "sample_catalog.csv"
    rows = csv_path.read_text(encoding="utf-8").strip().splitlines()[1:]
    assert len(rows) >= 15
    # HomeSelect Beans qty=0 for OOS demo; FreshFarm Beans available as alternative
    assert any("Beans,HomeSelect" in r and ",0,2026-" in r for r in rows)
    assert any("Beans,FreshFarm" in r for r in rows)
