from __future__ import annotations

from typing import Any

from shared.config import get_settings


from services.merchant_agent.graph.availability import has_unavailable_items


def conditional_executor(state: dict[str, Any]) -> str:
    if state.get("react_loop_capped"):
        return "suggest_alternative" if has_unavailable_items(state) else "check_availability"
    if state.get("react_should_continue"):
        return "react_planner"
    return "suggest_alternative" if has_unavailable_items(state) else "check_availability"


async def executor(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    settings = get_settings()
    loop_max = max(1, int(settings.react_loop_max))
    loop_count = int(state.get("react_loop_count", 0))

    if loop_count >= loop_max:
        async with deps.session_factory() as db_session:
            await deps.memory_store.append_audit(
                db_session,
                session_id=state["session_id"],
                actor="merchant_agent",
                action="REACT_LOOP_CAPPED",
                detail={"loop_max": loop_max, "react_scratchpad": state.get("react_scratchpad", [])},
            )
            await db_session.commit()
        return {"react_loop_capped": True, "react_selected_tools": [], "react_should_continue": False}

    selected_tools = list(state.get("react_selected_tools", []))
    if not selected_tools:
        return {"react_loop_count": loop_count + 1, "react_should_continue": False}

    updates: dict[str, Any] = {"react_loop_count": loop_count + 1, "react_should_continue": True}
    audit_events: list[tuple[str, dict[str, Any]]] = []
    resolved_item_ids = [item.get("item_id") for item in state.get("line_items", []) if item.get("item_id")]

    if "offer_lookup" in selected_tools:
        offers_by_id: dict[str, dict[str, Any]] = {}
        for item_id in resolved_item_ids:
            try:
                offers = await deps.offer_lookup_tool.by_item(item_id)
            except Exception:
                offers = []
            for offer in offers:
                offer_id = str(offer.get("id") or "")
                if offer_id:
                    offers_by_id[offer_id] = offer
        updates["resolved_offers"] = list(offers_by_id.values())
        audit_events.append(
            (
                "OFFER_SURFACED",
                {
                    "item_ids": resolved_item_ids,
                    "offer_ids": sorted(offers_by_id.keys()),
                    "offer_count": len(offers_by_id),
                },
            )
        )

    if "campaign_orchestrator_scan" in selected_tools:
        try:
            campaigns = await deps.campaign_orchestrator_scan_tool.scan(resolved_item_ids)
        except Exception:
            campaigns = []
        updates["campaign_context"] = campaigns
        audit_events.append(
            (
                "CAMPAIGN_SURFACED",
                {
                    "item_ids": resolved_item_ids,
                    "campaign_count": len(campaigns),
                    "campaign_ids": [str(campaign.get("id")) for campaign in campaigns if campaign.get("id")],
                },
            )
        )

    if "cross_sell_lookup" in selected_tools:
        from services.merchant_agent.graph.availability import unavailable_items_from_state

        unavailable_items = unavailable_items_from_state(state)
        cross_sell_candidates: list[dict[str, Any]] = []
        source_item_ids: list[str] = []
        if unavailable_items:
            async with deps.session_factory() as db_session:
                for unavailable in unavailable_items:
                    source_item_id = unavailable.get("item_id")
                    if not source_item_id:
                        continue
                    source_item_ids.append(str(source_item_id))
                    rows = await deps.cross_sell_lookup_tool.for_item(db_session, source_item_id)
                    cross_sell_candidates.extend(rows)
        else:
            unavailable = state.get("unavailable_item") or {}
            source_item_id = unavailable.get("item_id")
            if source_item_id:
                source_item_ids.append(str(source_item_id))
                async with deps.session_factory() as db_session:
                    cross_sell_candidates = await deps.cross_sell_lookup_tool.for_item(db_session, source_item_id)
        updates["cross_sell_candidates"] = cross_sell_candidates
        audit_events.append(
            (
                "CROSS_SELL_SURFACED",
                {
                    "source_item_ids": source_item_ids,
                    "candidate_count": len(cross_sell_candidates),
                    "target_item_ids": [
                        target_id
                        for row in cross_sell_candidates
                        for target_id in row.get("target_item_ids", [])
                    ],
                },
            )
        )

    if audit_events:
        async with deps.session_factory() as db_session:
            for action, detail in audit_events:
                await deps.memory_store.append_audit(
                    db_session,
                    session_id=state["session_id"],
                    actor="merchant_agent",
                    action=action,
                    detail=detail,
                )
            await db_session.commit()

    updates["react_selected_tools"] = []
    return updates
