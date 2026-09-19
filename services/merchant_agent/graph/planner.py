from __future__ import annotations

from typing import Any


async def planner(state: dict[str, Any], _deps: Any) -> dict[str, Any]:
    scratchpad = list(state.get("react_scratchpad", []))
    attempted_goals = {str(entry.get("goal")) for entry in scratchpad if isinstance(entry, dict)}
    resolved_item_ids = [item.get("item_id") for item in state.get("line_items", []) if item.get("item_id")]
    unavailable = state.get("unavailable_item")
    goal = "done"

    if unavailable and "cross_sell_lookup" not in attempted_goals:
        goal = "cross_sell_lookup"
    elif resolved_item_ids and "offer_lookup" not in attempted_goals:
        goal = "offer_lookup"
    elif resolved_item_ids and "campaign_scan" not in attempted_goals:
        goal = "campaign_scan"

    scratchpad.append(
        {
            "step": len(scratchpad) + 1,
            "goal": goal,
            "item_ids": resolved_item_ids,
            "has_unavailable_item": bool(unavailable),
        }
    )
    return {"react_goal": goal, "react_scratchpad": scratchpad}
