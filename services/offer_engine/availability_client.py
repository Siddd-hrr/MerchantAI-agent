from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass

import httpx

from shared.config import get_settings


@dataclass(frozen=True)
class TrueAvailability:
    item_id: str
    true_available_qty: int


class AvailabilityLookupError(RuntimeError):
    """Raised when true-availability could not be fetched for at least one item."""


class AvailabilityClient:
    def __init__(self, base_url: str | None = None) -> None:
        settings = get_settings()
        self._base_url = (base_url or f"http://localhost:{settings.admin_port}").rstrip("/")

    async def get_true_available(self, item_id: str) -> TrueAvailability:
        url = f"{self._base_url}/internal/items/{item_id}/true-available"
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, dict):
            raise AvailabilityLookupError(f"Invalid true-availability payload for item {item_id}")

        true_available_qty = max(0, int(payload.get("true_available_qty", 0)))
        payload_item_id = str(payload.get("item_id", item_id))
        return TrueAvailability(item_id=payload_item_id, true_available_qty=true_available_qty)

    async def get_true_available_qty_map(
        self, item_ids: Iterable[str], *, raise_on_error: bool = False
    ) -> dict[str, int]:
        normalized_item_ids = [str(item_id) for item_id in item_ids if str(item_id)]
        unique_item_ids = list(dict.fromkeys(normalized_item_ids))
        if not unique_item_ids:
            return {}

        lookups = await asyncio.gather(
            *(self.get_true_available(item_id) for item_id in unique_item_ids),
            return_exceptions=True,
        )

        qty_by_item_id: dict[str, int] = {}
        failed_item_ids: list[str] = []
        for item_id, lookup_result in zip(unique_item_ids, lookups, strict=False):
            if isinstance(lookup_result, Exception):
                failed_item_ids.append(item_id)
                continue
            qty_by_item_id[item_id] = lookup_result.true_available_qty

        if failed_item_ids and raise_on_error:
            failed_text = ", ".join(failed_item_ids)
            raise AvailabilityLookupError(f"Could not fetch true availability for item IDs: {failed_text}")

        return qty_by_item_id
