from __future__ import annotations

from typing import Any

import httpx

from shared.config import get_settings


class OfferLookupTool:
    def __init__(self, base_url: str | None = None) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.offer_engine_url).rstrip("/")

    async def by_item(self, item_id: str) -> list[dict[str, Any]]:
        url = f"{self._base_url}/offers/by-item/{item_id}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        offers = payload.get("offers", []) if isinstance(payload, dict) else []
        return [offer for offer in offers if isinstance(offer, dict)]

    async def list_saved(self, offer_type: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if offer_type:
            params["offer_type"] = offer_type.upper()
        url = f"{self._base_url}/offers/saved"
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, params=params or None)
            response.raise_for_status()
            payload = response.json()
        offers = payload.get("offers", []) if isinstance(payload, dict) else []
        return [offer for offer in offers if isinstance(offer, dict)]
