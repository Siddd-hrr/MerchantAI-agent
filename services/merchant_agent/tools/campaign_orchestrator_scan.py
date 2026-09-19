from __future__ import annotations

from typing import Any

from services.merchant_agent.tools.offer_lookup import OfferLookupTool

_CAMPAIGN_TYPES = {"FESTIVAL_CAMPAIGN", "COMBO"}


class CampaignOrchestratorScanTool:
    def __init__(self, offer_lookup_tool: OfferLookupTool) -> None:
        self._offer_lookup_tool = offer_lookup_tool

    async def scan(self, item_ids: list[str]) -> list[dict[str, Any]]:
        relevant: dict[str, dict[str, Any]] = {}
        for item_id in item_ids:
            offers = await self._offer_lookup_tool.by_item(item_id)
            for offer in offers:
                if str(offer.get("offer_type", "")).upper() not in _CAMPAIGN_TYPES:
                    continue
                offer_id = str(offer.get("id") or "")
                if not offer_id:
                    continue
                relevant[offer_id] = offer
        return list(relevant.values())
