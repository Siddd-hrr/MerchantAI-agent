from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from services.merchant_agent.graph.nodes import NodeDependencies, suggest_alternative
from services.merchant_agent.tools.generate_creative_promo import STUB_PROMO_TEXT, _coerce_response_text


class _FailingLLM:
    async def ainvoke(self, *_args, **_kwargs) -> str:
        raise RuntimeError("429 rate limit")


class _FakeSession:
    async def commit(self) -> None:
        return None


class _FakeSessionFactory:
    async def __aenter__(self) -> _FakeSession:
        return _FakeSession()

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


class _FakeMemoryStore:
    def __init__(self) -> None:
        self.audit_events: list[dict[str, Any]] = []

    async def append_audit(self, _db_session, *, session_id: str, actor: str, action: str, detail: dict[str, Any]) -> None:
        self.audit_events.append({"session_id": session_id, "actor": actor, "action": action, "detail": detail})


@dataclass
class _FakeCrossSellLookupTool:
    rows: list[dict[str, Any]]

    async def for_item(self, _db_session, _item_id: str) -> list[dict[str, Any]]:
        return self.rows


class _FakeCatalogService:
    async def get_item_by_id(self, _db_session, item_id: str) -> dict[str, Any] | None:
        if item_id == "target-1":
            return {
                "item_id": "target-1",
                "name": "Beans",
                "brand": "FreshFarm",
                "price_paise": 1300,
                "available_qty": 8,
            }
        return None

    async def find_alternatives(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("same-name fallback should not be used when cross-sell exists")


@pytest.mark.asyncio
async def test_cross_sell_preferred_and_promo_stub_on_llm_failure() -> None:
    memory = _FakeMemoryStore()
    deps = NodeDependencies(
        llm=_FailingLLM(),
        session_factory=lambda: _FakeSessionFactory(),
        catalog_service=_FakeCatalogService(),  # type: ignore[arg-type]
        memory_store=memory,  # type: ignore[arg-type]
        invoice_service=None,  # type: ignore[arg-type]
        personal_memory_store=None,  # type: ignore[arg-type]
        reservation_client=None,
        payment_client=None,
        offer_lookup_tool=None,
        cross_sell_lookup_tool=_FakeCrossSellLookupTool(
            rows=[{"source_item_id": "source-1", "target_item_ids": ["target-1"], "priority": 10}]
        ),
        campaign_orchestrator_scan_tool=None,
    )
    state = {
        "session_id": "s-x",
        "unavailable_item": {
            "item_id": "source-1",
            "item_name": "Beans",
            "brand": "HomeSelect",
            "requested_qty": 2,
        },
        "cross_sell_candidates": [],
    }

    updates = await suggest_alternative(state, deps)

    assert updates["catalog_suggestions"][0]["item_id"] == "target-1"
    assert "Warning: HomeSelect Beans is not available" in updates["reply"]
    assert updates["reply"].strip().endswith(STUB_PROMO_TEXT)
    assert memory.audit_events[-1]["action"] == "ITEM_UNAVAILABLE"


def test_coerce_response_text_strips_gemini_thinking_blocks() -> None:
    class _FakeResponse:
        content = [
            {
                "type": "thinking",
                "thinking": "* Goal: write promo line\n* Option A: test",
            },
            "We've replaced your beans with delicious FreshFarm Beans.",
        ]

    assert (
        _coerce_response_text(_FakeResponse())
        == "We've replaced your beans with delicious FreshFarm Beans."
    )
