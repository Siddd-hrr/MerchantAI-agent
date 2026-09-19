from __future__ import annotations

import pytest

from services.merchant_agent.tools.offer_lookup import OfferLookupTool


@pytest.mark.asyncio
async def test_offer_lookup_by_item_calls_offer_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "offers": [
                    {"id": "offer-1", "description": "10% off", "offer_type": "DISCOUNT"},
                    {"id": "offer-2", "description": "Combo deal", "offer_type": "COMBO"},
                ]
            }

    async def fake_get(self, url: str, *args, **kwargs):  # noqa: ANN001
        captured["url"] = url
        return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    tool = OfferLookupTool(base_url="http://localhost:8004")
    offers = await tool.by_item("item-123")

    assert captured["url"] == "http://localhost:8004/offers/by-item/item-123"
    assert len(offers) == 2
    assert offers[0]["id"] == "offer-1"
