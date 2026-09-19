from __future__ import annotations

from typing import Any


async def tool_selector(state: dict[str, Any], _deps: Any) -> dict[str, Any]:
    goal = state.get("react_goal") or "done"
    tools: list[str] = []

    if goal == "offer_lookup":
        tools = ["offer_lookup"]
    elif goal == "campaign_scan":
        tools = ["campaign_orchestrator_scan"]
    elif goal == "cross_sell_lookup":
        tools = ["cross_sell_lookup"]

    return {"react_selected_tools": tools}
