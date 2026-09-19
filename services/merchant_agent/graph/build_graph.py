from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from services.merchant_agent.graph.availability import has_unavailable_items
from services.merchant_agent.graph.executor import conditional_executor
from services.merchant_agent.graph.nodes import (
    NodeDependencies,
    ask_for_fields,
    check_availability,
    check_missing_fields,
    dispatch_invoice_processing,
    finalize_order,
    generate_invoice,
    load_session,
    off_topic_guard,
    offer_invoice_confirmation,
    parse_intent,
    resolve_catalog,
    resolve_invoice_confirmation,
    run_react_executor,
    run_react_planner,
    run_react_tool_selector,
    suggest_alternative,
    resolve_invoice_outcome,
)
from services.merchant_agent.graph.state import OrderState

NodeFn = Callable[[dict[str, Any], NodeDependencies], Awaitable[dict[str, Any]]]


def _with_persistence(node_fn: NodeFn, deps: NodeDependencies) -> Callable[[OrderState], Awaitable[dict[str, Any]]]:
    async def _run(state: OrderState) -> dict[str, Any]:
        updates = await node_fn(dict(state), deps)
        merged = dict(state)
        merged.update(updates)
        await deps.memory_store.save_state(merged["session_id"], merged)
        return updates

    return _run


def build_graph(deps: NodeDependencies):
    graph = StateGraph(OrderState)

    graph.add_node("load_session", _with_persistence(load_session, deps))
    graph.add_node("off_topic_guard", _with_persistence(off_topic_guard, deps))
    graph.add_node("parse_intent", _with_persistence(parse_intent, deps))
    graph.add_node("resolve_invoice_confirmation", _with_persistence(resolve_invoice_confirmation, deps))
    graph.add_node("resolve_catalog", _with_persistence(resolve_catalog, deps))
    graph.add_node("react_planner", _with_persistence(run_react_planner, deps))
    graph.add_node("react_tool_selector", _with_persistence(run_react_tool_selector, deps))
    graph.add_node("react_executor", _with_persistence(run_react_executor, deps))
    graph.add_node("check_availability", _with_persistence(check_availability, deps))
    graph.add_node("suggest_alternative", _with_persistence(suggest_alternative, deps))
    graph.add_node("check_missing_fields", _with_persistence(check_missing_fields, deps))
    graph.add_node("ask_for_fields", _with_persistence(ask_for_fields, deps))
    graph.add_node("offer_invoice_confirmation", _with_persistence(offer_invoice_confirmation, deps))
    graph.add_node("finalize_order", _with_persistence(finalize_order, deps))
    graph.add_node("generate_invoice", _with_persistence(generate_invoice, deps))
    graph.add_node("dispatch_invoice_processing", _with_persistence(dispatch_invoice_processing, deps))
    graph.add_node("resolve_invoice_outcome", _with_persistence(resolve_invoice_outcome, deps))

    graph.add_edge(START, "load_session")
    graph.add_edge("load_session", "off_topic_guard")

    def _off_topic_route(state: dict[str, Any]) -> str:
        return END if state.get("off_topic") else "parse_intent"

    graph.add_conditional_edges("off_topic_guard", _off_topic_route, {END: END, "parse_intent": "parse_intent"})
    graph.add_edge("parse_intent", "resolve_invoice_confirmation")
    graph.add_edge("resolve_invoice_confirmation", "resolve_catalog")
    graph.add_edge("resolve_catalog", "react_planner")
    graph.add_edge("react_planner", "react_tool_selector")
    graph.add_edge("react_tool_selector", "react_executor")
    graph.add_conditional_edges(
        "react_executor",
        conditional_executor,
        {
            "react_planner": "react_planner",
            "check_availability": "check_availability",
            "suggest_alternative": "suggest_alternative",
        },
    )

    def _availability_route(state: dict[str, Any]) -> str:
        if has_unavailable_items(state):
            return "suggest_alternative"
        return "check_missing_fields"

    graph.add_conditional_edges(
        "check_availability",
        _availability_route,
        {"suggest_alternative": "suggest_alternative", "check_missing_fields": "check_missing_fields"},
    )

    graph.add_edge("suggest_alternative", END)

    def _missing_route(state: dict[str, Any]) -> str:
        if state.get("invoice_proceed"):
            return "finalize_order"
        if state.get("missing_fields"):
            return "ask_for_fields"
        if any(
            item.get("catalog_status") == "stockout_pending"
            for item in state.get("line_items") or []
        ):
            return "ask_for_fields"
        # not_found items are excluded; ambiguous lines do not block when other lines are confirmed.
        orderable = [
            item
            for item in state.get("line_items") or []
            if item.get("resolved")
            and item.get("item_id")
            and item.get("qty") is not None
            and item.get("catalog_status") != "stockout_pending"
        ]
        blocking = [
            item
            for item in state.get("line_items") or []
            if not item.get("resolved")
            and item.get("catalog_status") not in ("not_found", "ambiguous")
        ]
        if blocking:
            return "ask_for_fields"
        if orderable and not state.get("missing_fields") and not state.get("awaiting_invoice_confirmation"):
            return "offer_invoice_confirmation"
        if not any(item.get("resolved") for item in state.get("line_items") or []):
            return "ask_for_fields"
        return "finalize_order"

    graph.add_conditional_edges(
        "check_missing_fields",
        _missing_route,
        {
            "ask_for_fields": "ask_for_fields",
            "offer_invoice_confirmation": "offer_invoice_confirmation",
            "finalize_order": "finalize_order",
        },
    )
    graph.add_edge("ask_for_fields", END)
    graph.add_edge("offer_invoice_confirmation", END)

    def _finalize_route(state: dict[str, Any]) -> str:
        return "suggest_alternative" if has_unavailable_items(state) else "generate_invoice"

    graph.add_conditional_edges(
        "finalize_order",
        _finalize_route,
        {"suggest_alternative": "suggest_alternative", "generate_invoice": "generate_invoice"},
    )
    graph.add_edge("generate_invoice", "dispatch_invoice_processing")
    graph.add_edge("dispatch_invoice_processing", "resolve_invoice_outcome")
    graph.add_edge("resolve_invoice_outcome", END)

    return graph.compile()
