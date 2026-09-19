from __future__ import annotations

from typing import Any


def unavailable_items_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    items = state.get("unavailable_items") or []
    if items:
        return [item for item in items if isinstance(item, dict)]
    single = state.get("unavailable_item")
    if isinstance(single, dict) and single:
        return [single]
    return []


def has_unavailable_items(state: dict[str, Any]) -> bool:
    return bool(unavailable_items_from_state(state))
