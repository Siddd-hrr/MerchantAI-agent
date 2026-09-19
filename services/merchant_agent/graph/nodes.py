from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from services.merchant_agent.memory.personal import PersonalMemoryStore
from services.merchant_agent.catalog_service import CatalogService
from services.merchant_agent.display_format import (
    format_expiry,
    format_inr_paise,
    format_price_per_unit,
    format_stock_qty,
)
from shared.catalog_fields import is_expired
from services.merchant_agent.promo_format import format_surfaced_promotions, merge_offers
from services.merchant_agent.graph.availability import unavailable_items_from_state
from services.merchant_agent.graph.executor import executor as react_executor
from services.merchant_agent.graph.planner import planner as react_planner
from services.merchant_agent.graph.tool_selector import tool_selector as react_tool_selector
from services.merchant_agent.invoice_service import InvoiceService
from services.merchant_agent.memory_store import MemoryStore
from shared.config import get_settings
from services.merchant_agent.persona import (
    MISSING_FIELDS_WARNING_TEMPLATE,
    NOT_IN_CATALOG_TEMPLATE,
    OFF_TOPIC_REDIRECT,
    OUT_OF_STOCK_WARNING_TEMPLATE,
    build_system_prompt,
)
from services.merchant_agent.tools.generate_creative_promo import STUB_PROMO_TEXT, _coerce_response_text, generate_creative_promo


class ParsedLineItem(BaseModel):
    item_name: str
    brand: str | None = None
    qty: int | None = None


class ParsedIntent(BaseModel):
    line_items: list[ParsedLineItem] = Field(default_factory=list)
    remove_item_names: list[str] = Field(default_factory=list)
    customer_name: str | None = None
    address: str | None = None
    phone: str | None = None


class OffTopicClassification(BaseModel):
    off_topic: bool = False


@dataclass
class NodeDependencies:
    llm: Any
    session_factory: Any
    catalog_service: CatalogService
    memory_store: MemoryStore
    invoice_service: InvoiceService
    personal_memory_store: PersonalMemoryStore
    reservation_client: Any | None
    payment_client: Any | None
    offer_lookup_tool: Any
    cross_sell_lookup_tool: Any
    campaign_orchestrator_scan_tool: Any


def _normalize_line_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_name": item.get("item_name", "").strip(),
        "brand": item.get("brand"),
        "qty": item.get("qty"),
        "item_id": item.get("item_id"),
        "unit_price_paise": item.get("unit_price_paise"),
        "available_qty": item.get("available_qty"),
        "weight_per_unit": item.get("weight_per_unit"),
        "expiry_date": item.get("expiry_date"),
        "resolved": bool(item.get("resolved", False)),
        "catalog_status": item.get("catalog_status"),
    }


def _apply_default_qty(line_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use qty 1 when the shopper named a product but did not specify quantity."""
    for item in line_items:
        if item.get("qty") is not None:
            continue
        if item.get("catalog_status") == "not_found":
            continue
        if not item.get("item_name"):
            continue
        has_identity = bool(item.get("brand")) or bool(item.get("item_id")) or item.get("resolved")
        if has_identity:
            item["qty"] = 1
    return line_items


def _dedupe_missing_fields(fields: list[str]) -> list[str]:
    deduped: list[str] = []
    for field_name in fields:
        if field_name not in deduped:
            deduped.append(field_name)
    return deduped


def _offer_target_subtotal_paise(offer: dict[str, Any], line_items: list[dict[str, Any]]) -> int:
    item_ids = {str(item_id) for item_id in offer.get("item_ids") or []}
    if not item_ids:
        return sum(int(item.get("qty", 0)) * int(item.get("unit_price_paise", 0)) for item in line_items)
    return sum(
        int(item.get("qty", 0)) * int(item.get("unit_price_paise", 0))
        for item in line_items
        if str(item.get("item_id")) in item_ids
    )


def _build_accepted_offers(state: dict[str, Any]) -> list[dict[str, Any]]:
    line_items = state.get("line_items", [])
    accepted: list[dict[str, Any]] = []
    for offer in state.get("resolved_offers", []):
        offer_id = offer.get("id")
        if not offer_id:
            continue
        discount_type = str(offer.get("discount_type", "")).upper()
        value = int(offer.get("value", 0))
        subtotal = _offer_target_subtotal_paise(offer, line_items)
        if subtotal <= 0:
            continue

        if discount_type in {"PERCENT", "CASHBACK"}:
            saved = max((subtotal * value) // 100, 0)
        else:
            saved = max(value, 0)
        accepted.append(
            {
                "id": str(offer_id),
                "description": str(offer.get("description", "")),
                "amount_saved_paise": saved,
            }
        )
    return accepted


async def _call_structured(llm: Any, schema: type[BaseModel], prompt: str) -> BaseModel:
    if hasattr(llm, "with_structured_output"):
        structured = llm.with_structured_output(schema)
        result = await structured.ainvoke(prompt)
        if isinstance(result, schema):
            return result
        if isinstance(result, dict):
            return schema(**result)

    raw = await llm.ainvoke(prompt)
    if isinstance(raw, schema):
        return raw
    if isinstance(raw, dict):
        return schema(**raw)
    text = _coerce_response_text(raw)
    if text:
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return schema(**parsed)
        except json.JSONDecodeError:
            pass
    return schema()


async def off_topic_guard(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    prompt = (
        f"{build_system_prompt()}\n\n"
        "Classify whether this message is unrelated to order placement. "
        "Return JSON: {\"off_topic\": true|false}.\n"
        f"Message: {state.get('message', '')}"
    )
    result = await _call_structured(deps.llm, OffTopicClassification, prompt)
    if result.off_topic:
        return {
            "off_topic": True,
            "status": "AWAITING_FIELDS",
            "reply": OFF_TOPIC_REDIRECT,
        }
    return {"off_topic": False}


async def load_session(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    session_id = state["session_id"]
    persisted_state = await deps.memory_store.load_state(session_id)
    persisted_draft = await deps.memory_store.load_order_draft(session_id)

    merged = dict(persisted_state or {})
    # Preserve known cart / customer fields across turns; only overwrite with non-empty incoming values.
    incoming = dict(state)
    for sticky in ("line_items", "customer_name", "address", "phone", "missing_fields", "catalog_suggestions"):
        incoming.pop(sticky, None)
    merged.update(incoming)

    if persisted_draft:
        for field_name in ["line_items", "customer_name", "address", "phone", "missing_fields", "status"]:
            if field_name == "line_items":
                if not merged.get("line_items") and persisted_draft.get("line_items"):
                    merged["line_items"] = persisted_draft["line_items"]
                continue
            if not merged.get(field_name) and persisted_draft.get(field_name):
                merged[field_name] = persisted_draft[field_name]

    merged.setdefault("line_items", [])
    merged.setdefault("catalog_suggestions", [])
    merged.setdefault("missing_fields", [])
    merged.setdefault("status", "DRAFT")
    merged.setdefault("reply", "")
    merged.setdefault("invoice", None)
    merged.setdefault("error", None)
    merged.setdefault("awaiting_invoice_confirmation", False)
    merged["invoice_proceed"] = False
    merged["resolved_offers"] = []
    merged["cross_sell_candidates"] = []
    merged["campaign_context"] = []
    merged.setdefault("personal_memory_snapshot", {})
    merged.setdefault("merchant_id", None)
    merged.setdefault("reservation_result", None)
    merged.setdefault("payment_result", None)
    merged.setdefault("payment_link_url", None)
    merged.setdefault("payment_expires_at", None)
    merged.setdefault("reservation_expires_at", None)
    merged["react_scratchpad"] = []
    merged["react_loop_count"] = 0
    merged["react_selected_tools"] = []
    merged["react_loop_capped"] = False
    merged["react_should_continue"] = False
    # Stale stockout flags from a prior turn are re-evaluated in this graph run.
    merged["unavailable_item"] = None
    merged["unavailable_items"] = []

    async with deps.session_factory() as db_session:
        personal_memory = await deps.personal_memory_store.list_by_consumer(
            db_session, consumer_agent_id=merged["consumer_agent_id"]
        )
    merged["personal_memory_snapshot"] = personal_memory

    return merged


def _names_similar(a: str, b: str) -> bool:
    left = "".join(ch for ch in a.lower() if ch.isalnum())
    right = "".join(ch for ch in b.lower() if ch.isalnum())
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    # edit distance <= 1 for typo merges (milk/millk)
    prev = list(range(len(right) + 1))
    for i, ch_l in enumerate(left, start=1):
        curr = [i]
        for j, ch_r in enumerate(right, start=1):
            cost = 0 if ch_l == ch_r else 1
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1] <= 1


def _detect_removed_item_names(message: str) -> list[str]:
    """Rule backup when user cancels a product (LLM may miss sticky-session removals)."""
    text = (message or "").strip().lower()
    if not text:
        return []
    patterns = [
        r"\bno\s+([a-z][a-z0-9\s-]{0,40}?)\s+required\b",
        r"\bno\s+([a-z][a-z0-9\s-]{0,40}?)\s+needed\b",
        r"\bdon'?t\s+want\s+([a-z][a-z0-9\s-]{0,40}?)\b",
        r"\bdo\s+not\s+want\s+([a-z][a-z0-9\s-]{0,40}?)\b",
        r"\bremove\s+([a-z][a-z0-9\s-]{0,40}?)\b",
        r"\bcancel\s+([a-z][a-z0-9\s-]{0,40}?)\b",
        r"\bwithout\s+([a-z][a-z0-9\s-]{0,40}?)\b",
        r"\bskip\s+([a-z][a-z0-9\s-]{0,40}?)\b",
    ]
    found: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            name = re.sub(r"\s+", " ", match.group(1)).strip(" .,!;:")
            # Drop trailing filler words that often trail the product noun.
            name = re.sub(r"\b(please|thanks|thank you|anymore|now)\b", "", name).strip()
            if name and name not in found:
                found.append(name)
    return found


def _drop_removed_line_items(
    line_items: list[dict[str, Any]], remove_names: list[str]
) -> list[dict[str, Any]]:
    if not remove_names:
        return line_items
    kept: list[dict[str, Any]] = []
    for item in line_items:
        item_name = str(item.get("item_name") or "")
        brand = str(item.get("brand") or "")
        full = f"{brand} {item_name}".strip()
        drop = False
        for remove_name in remove_names:
            if not remove_name:
                continue
            if _names_similar(item_name, remove_name) or _names_similar(full, remove_name):
                drop = True
                break
            # "no milk" should also match item_name milk even if brand set later.
            if remove_name in item_name.lower() or item_name.lower() in remove_name:
                drop = True
                break
        if not drop:
            kept.append(item)
    return kept


_SUBSTITUTE_HINTS = (
    "select",
    "choose",
    "switch",
    "instead",
    "replace",
    "go with",
    "i'll take",
    "ill take",
    "use ",
    "okk",
    "ok ",
)

_CATALOG_PRODUCT_RE = re.compile(
    r"\b(?P<brand>freshfarm|homeselect|dairygold|amul|fortune|madhur|nandini|tata\s+sampann|24\s+mantra)"
    r"\s+(?P<product>kidney\s+beans|beans|milk|rice|sugar|curd|poha)\b",
    re.I,
)

_BRAND_CANONICAL = {
    "freshfarm": "FreshFarm",
    "homeselect": "HomeSelect",
    "dairygold": "DairyGold",
    "amul": "Amul",
    "fortune": "Fortune",
    "madhur": "Madhur",
    "nandini": "Nandini",
    "tata sampann": "Tata Sampann",
    "24 mantra": "24 Mantra",
}


def _canonical_product(name: str) -> str:
    normalized = re.sub(r"\s+", " ", name.strip().lower())
    mapping = {
        "kidney beans": "Kidney Beans",
        "beans": "Beans",
        "milk": "Milk",
        "rice": "Rice",
        "sugar": "Sugar",
        "curd": "Curd",
        "poha": "Poha",
    }
    return mapping.get(normalized, name.strip().title())


def _extract_qty_from_message(message: str, *, after_index: int = 0) -> int | None:
    tail = message[after_index:]
    for pattern in (r"\bqty\s*(\d+)\b", r"\b(\d+)\s*(?:packs?|units?|kg|l)?\b"):
        match = re.search(pattern, tail, flags=re.I)
        if match:
            return int(match.group(1))
    return None


def _apply_substitute_phrase(line_items: list[dict[str, Any]], message: str) -> list[dict[str, Any]]:
    """Rule-based brand swap when shopper picks in-stock alternatives (supports multiple lines)."""
    text = (message or "").strip()
    if not text:
        return line_items

    matches = list(_CATALOG_PRODUCT_RE.finditer(text))
    if not matches:
        return line_items

    has_pending = any(item.get("catalog_status") == "stockout_pending" for item in line_items)
    if not has_pending and not any(hint in text.lower() for hint in _SUBSTITUTE_HINTS):
        return line_items

    for index, match in enumerate(matches):
        brand_key = re.sub(r"\s+", " ", match.group("brand").strip().lower())
        product = _canonical_product(match.group("product"))
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        qty = _extract_qty_from_message(text[match.start() : segment_end], after_index=0)

        target_idx = next(
            (
                idx
                for idx, item in enumerate(line_items)
                if item.get("catalog_status") == "stockout_pending"
                and _names_similar(item.get("item_name", ""), product)
            ),
            None,
        )
        if target_idx is None:
            target_idx = next(
                (
                    idx
                    for idx, item in enumerate(line_items)
                    if item.get("catalog_status") == "stockout_pending"
                ),
                None,
            )
        if target_idx is None:
            continue

        item = line_items[target_idx]
        item["brand"] = _BRAND_CANONICAL.get(brand_key, match.group("brand").strip().title())
        item["item_name"] = product
        if qty is not None:
            item["qty"] = qty
        item["resolved"] = False
        item["item_id"] = None
        item["catalog_status"] = None
    return line_items


async def _offers_for_item_ids(deps: NodeDependencies, item_ids: list[str]) -> list[dict[str, Any]]:
    if deps.offer_lookup_tool is None:
        return []
    offer_by_id: dict[str, dict[str, Any]] = {}
    for item_id in item_ids:
        if not item_id:
            continue
        try:
            offers = await deps.offer_lookup_tool.by_item(item_id)
        except Exception:
            offers = []
        for offer in offers:
            offer_id = str(offer.get("id") or "")
            if offer_id:
                offer_by_id[offer_id] = offer
    return list(offer_by_id.values())


_INVOICE_PROCEED_PHRASES = (
    "proceed",
    "go ahead",
    "create invoice",
    "generate invoice",
    "confirm order",
    "yes",
    "looks good",
    "ok proceed",
    "okay proceed",
    "invoice please",
    "place order",
    "complete order",
)

_ADD_MORE_PHRASES = (
    "add ",
    "also want",
    "order more",
    "something else",
    "another ",
    "change order",
    "modify order",
    "not yet",
    "wait",
)


def _is_invoice_proceed_message(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    return any(phrase in text for phrase in _INVOICE_PROCEED_PHRASES)


def _is_add_more_order_message(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    return any(phrase in text for phrase in _ADD_MORE_PHRASES)


async def _active_store_campaigns(deps: NodeDependencies) -> list[dict[str, Any]]:
    if deps.offer_lookup_tool is None:
        return []
    campaigns: list[dict[str, Any]] = []
    for offer_type in ("FESTIVAL_CAMPAIGN", "COMBO", "DISCOUNT", "COUPON"):
        try:
            campaigns.extend(await deps.offer_lookup_tool.list_saved(offer_type=offer_type))
        except Exception:
            continue
    return merge_offers(campaigns)


def _format_order_confirmation_summary(state: dict[str, Any]) -> str:
    sections: list[str] = [
        "📋 All required order details are collected.",
        "",
        "Order summary:",
    ]
    for item in _orderable_line_items(state):
        label = item.get("item_name") or "item"
        if item.get("brand"):
            label = f"{item['brand']} {label}"
        sections.append(f"• {label} x{item.get('qty', 1)}")
    sections.extend(
        [
            "",
            f"Customer: {state.get('customer_name') or '—'}",
            f"Phone: {state.get('phone') or '—'}",
            f"Address: {state.get('address') or '—'}",
        ]
    )
    return "\n".join(sections)


async def resolve_invoice_confirmation(state: dict[str, Any], _deps: NodeDependencies) -> dict[str, Any]:
    if not state.get("awaiting_invoice_confirmation"):
        return {}
    message = str(state.get("message") or "")
    if _is_invoice_proceed_message(message):
        return {"awaiting_invoice_confirmation": False, "invoice_proceed": True}
    if _is_add_more_order_message(message):
        return {"awaiting_invoice_confirmation": False, "invoice_proceed": False}
    # New details or items — re-evaluate the cart before offering invoice again.
    return {"awaiting_invoice_confirmation": False, "invoice_proceed": False}


async def offer_invoice_confirmation(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    orderable = _orderable_line_items(state)
    if not orderable:
        return {
            "status": "AWAITING_FIELDS",
            "reply": "No catalog-confirmed items are ready to invoice yet.",
        }

    store_campaigns = await _active_store_campaigns(deps)
    promotions_block = format_surfaced_promotions(
        state.get("resolved_offers") or [],
        merge_offers(state.get("campaign_context") or [], store_campaigns),
    )

    sections = [_format_order_confirmation_summary(state)]
    if promotions_block:
        sections.extend(["", promotions_block])
    sections.extend(
        [
            "",
            "Would you like to proceed with invoice creation, or order something else?",
            "Reply **Proceed** to generate the invoice, or tell me any additional items to add.",
        ]
    )
    reply = "\n".join(sections)

    async with deps.session_factory() as db_session:
        await deps.memory_store.append_audit(
            db_session,
            session_id=state["session_id"],
            actor="merchant_agent",
            action="INVOICE_CONFIRMATION_OFFERED",
            detail={
                "line_items": orderable,
                "campaign_count": len(store_campaigns),
                "offer_count": len(state.get("resolved_offers") or []),
            },
        )
        await db_session.commit()

    return {
        "reply": reply,
        "status": "AWAITING_CONFIRMATION",
        "awaiting_invoice_confirmation": True,
        "invoice_proceed": False,
        "catalog_suggestions": [],
    }


async def parse_intent(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    known_summary = {
        "line_items": [
            {"item_name": i.get("item_name"), "brand": i.get("brand"), "qty": i.get("qty"), "resolved": i.get("resolved")}
            for i in state.get("line_items", [])
        ],
        "customer_name": state.get("customer_name"),
        "address": state.get("address"),
        "phone": state.get("phone"),
    }
    prompt = (
        f"{build_system_prompt()}\n\n"
        "Extract NEW or UPDATED order fields from the latest message into JSON with keys: "
        "line_items[{item_name,brand,qty}], remove_item_names[], customer_name, address, phone. "
        "Rules:\n"
        "- item_name must be the product only (e.g. 'Milk'), NEVER include brand in item_name.\n"
        "- Put brand in the brand field (e.g. Amul, DairyGold).\n"
        "- Do not clear fields that are already known unless the user explicitly changes them.\n"
        "- If the user cancels a product (e.g. 'no milk required', 'remove beans', 'don't want milk'), "
        "put that product name in remove_item_names and do NOT keep it in line_items.\n"
        "- Use nulls only when the message does not provide that value.\n"
        f"Already known: {json.dumps(known_summary)}\n"
        f"Latest message: {state.get('message', '')}"
    )
    parsed = await _call_structured(deps.llm, ParsedIntent, prompt)

    remove_names = [
        *(parsed.remove_item_names or []),
        *_detect_removed_item_names(str(state.get("message") or "")),
    ]

    merged_items = [_normalize_line_item(item) for item in state.get("line_items", [])]
    for extracted in parsed.line_items:
        extracted_name = (extracted.item_name or "").strip()
        extracted_brand = (extracted.brand or None)
        if extracted_name and any(
            _names_similar(extracted_name, remove_name)
            or extracted_name.lower() in remove_name.lower()
            or remove_name.lower() in extracted_name.lower()
            for remove_name in remove_names
            if remove_name
        ):
            continue
        # If model stuffed brand into item_name, split when possible.
        name_parts = extracted_name.split()
        if extracted_brand is None and len(name_parts) >= 2:
            maybe_brand, *rest = name_parts
            if rest:
                extracted_brand = maybe_brand
                extracted_name = " ".join(rest)

        existing = next(
            (item for item in merged_items if _names_similar(item.get("item_name", ""), extracted_name)),
            None,
        )
        if existing:
            existing["item_name"] = extracted_name or existing.get("item_name")
            if extracted_brand:
                existing["brand"] = extracted_brand
            existing["qty"] = extracted.qty if extracted.qty is not None else existing.get("qty")
            # Re-resolve after updates (including brand swap for stockout alternatives).
            if extracted_name or extracted_brand or extracted.qty is not None:
                existing["resolved"] = False
                existing["item_id"] = None
                existing["catalog_status"] = None
        else:
            merged_items.append(
                {
                    "item_name": extracted_name,
                    "brand": extracted_brand,
                    "qty": extracted.qty,
                    "item_id": None,
                    "unit_price_paise": None,
                    "available_qty": None,
                    "resolved": False,
                }
            )

    # Cancelled products leave sticky session (LLM + phrase backup).
    merged_items = _drop_removed_line_items(merged_items, remove_names)

    # Drop unresolved placeholder duplicates once a richer similar row exists.
    cleaned: list[dict[str, Any]] = []
    for item in merged_items:
        dominated = False
        for other in merged_items:
            if other is item:
                continue
            if not _names_similar(item.get("item_name", ""), other.get("item_name", "")):
                continue
            item_score = int(bool(item.get("brand"))) + int(bool(item.get("qty"))) + int(bool(item.get("resolved")))
            other_score = int(bool(other.get("brand"))) + int(bool(other.get("qty"))) + int(bool(other.get("resolved")))
            if other_score > item_score and not item.get("resolved"):
                dominated = True
                break
        if not dominated:
            cleaned.append(item)

    cleaned = _apply_substitute_phrase(cleaned, str(state.get("message") or ""))
    cleaned = _apply_default_qty(cleaned)

    personal_snapshot = dict(state.get("personal_memory_snapshot") or {})
    customer_profile = personal_snapshot.get("customer_profile", {})

    return {
        "line_items": cleaned,
        "customer_name": parsed.customer_name or state.get("customer_name") or customer_profile.get("customer_name"),
        "address": parsed.address or state.get("address") or customer_profile.get("address"),
        "phone": parsed.phone or state.get("phone") or customer_profile.get("phone"),
    }


async def resolve_catalog(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    line_items = [_normalize_line_item(item) for item in state.get("line_items", [])]
    catalog_suggestions: list[dict[str, Any]] = []
    offer_by_id: dict[str, dict[str, Any]] = {}
    resolved_item_ids: list[str] = []
    campaign_context: list[dict[str, Any]] = []
    async with deps.session_factory() as db_session:
        for item in line_items:
            if item.get("catalog_status") == "stockout_pending":
                continue
            if not item.get("item_name"):
                item["catalog_status"] = "missing_name"
                continue
            matches = await deps.catalog_service.resolve_item(
                db_session,
                item_name=item["item_name"],
                brand=item.get("brand"),
            )
            if len(matches) == 1:
                match = matches[0]
            elif len(matches) > 1:
                match = deps.catalog_service.pick_best_match(matches, requested_qty=item.get("qty"))
            else:
                match = None

            if match is not None:
                item["item_id"] = match.item_id
                resolved_item_ids.append(match.item_id)
                item["item_name"] = match.name
                item["brand"] = match.brand
                item["weight_per_unit"] = match.weight_per_unit
                item["expiry_date"] = match.expiry_date
                item["unit_price_paise"] = match.price_paise
                item["available_qty"] = match.available_qty
                item["resolved"] = True
                item["catalog_status"] = "resolved"
            elif len(matches) == 0:
                item["resolved"] = False
                item["catalog_status"] = "not_found"
            else:
                item["resolved"] = False
                item["catalog_status"] = "ambiguous"
                for match in matches:
                    suggestion = match.model_dump()
                    if deps.offer_lookup_tool is not None:
                        try:
                            suggestion["promotions"] = await deps.offer_lookup_tool.by_item(match.item_id)
                        except Exception:
                            suggestion["promotions"] = []
                    else:
                        suggestion["promotions"] = []
                    catalog_suggestions.append(suggestion)
                    for promo in suggestion["promotions"]:
                        promo_id = str(promo.get("id") or "")
                        if promo_id:
                            offer_by_id[promo_id] = promo

    scan_item_ids = resolved_item_ids + [
        str(suggestion.get("item_id"))
        for suggestion in catalog_suggestions
        if suggestion.get("item_id")
    ]
    if scan_item_ids and deps.campaign_orchestrator_scan_tool is not None:
        try:
            campaign_context = await deps.campaign_orchestrator_scan_tool.scan(scan_item_ids)
        except Exception:
            campaign_context = []
        for campaign in campaign_context:
            campaign_id = str(campaign.get("id") or "")
            if campaign_id:
                offer_by_id[campaign_id] = campaign

    for item in line_items:
        item_id = item.get("item_id")
        if not item_id or deps.offer_lookup_tool is None:
            continue
        try:
            offers = await deps.offer_lookup_tool.by_item(item_id)
        except Exception:
            offers = []
        for offer in offers:
            offer_id = str(offer.get("id") or "")
            if offer_id:
                offer_by_id[offer_id] = offer

    if offer_by_id:
        async with deps.session_factory() as db_session:
            await deps.memory_store.append_audit(
                db_session,
                session_id=state["session_id"],
                actor="merchant_agent",
                action="OFFER_SURFACED",
                detail={
                    "source": "resolve_catalog",
                    "item_ids": resolved_item_ids,
                    "offer_ids": sorted(offer_by_id.keys()),
                    "offer_count": len(offer_by_id),
                },
            )
            await db_session.commit()

    line_items = _apply_default_qty(line_items)

    return {
        "line_items": line_items,
        "catalog_suggestions": catalog_suggestions,
        "resolved_offers": list(offer_by_id.values()),
        "campaign_context": campaign_context,
    }


async def check_availability(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    line_items = [_normalize_line_item(item) for item in state.get("line_items", [])]
    unavailable_items: list[dict[str, Any]] = []
    async with deps.session_factory() as db_session:
        for item in line_items:
            if not item.get("resolved") or not item.get("item_id") or not item.get("qty"):
                continue
            if item.get("catalog_status") == "stockout_pending":
                continue
            latest = await deps.catalog_service.get_item_by_id(db_session, item["item_id"])
            if not latest:
                continue
            if is_expired(latest.get("expiry_date")) or int(latest["available_qty"]) < int(item["qty"]):
                unavailable_items.append(
                    {
                        "item_id": item["item_id"],
                        "item_name": item["item_name"],
                        "brand": item["brand"],
                        "requested_qty": item["qty"],
                        "available_qty": latest["available_qty"],
                        "weight_per_unit": latest.get("weight_per_unit"),
                        "expiry_date": latest.get("expiry_date"),
                    }
                )
                continue
            item["available_qty"] = latest["available_qty"]
            item["unit_price_paise"] = latest["price_paise"]
            item["weight_per_unit"] = latest.get("weight_per_unit")
            item["expiry_date"] = latest.get("expiry_date")
    if unavailable_items:
        return {
            "line_items": line_items,
            "unavailable_items": unavailable_items,
            "unavailable_item": unavailable_items[0],
            "status": "AWAITING_FIELDS",
        }
    return {
        "line_items": line_items,
        "unavailable_items": [],
        "unavailable_item": None,
    }


async def run_react_planner(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    return await react_planner(state, deps)


async def run_react_tool_selector(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    return await react_tool_selector(state, deps)


async def run_react_executor(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    return await react_executor(state, deps)


def _mark_line_stockout_pending(
    line_items: list[dict[str, Any]], unavailable: dict[str, Any]
) -> list[dict[str, Any]]:
    """Hold the OOS line out of invoicing until the shopper picks a substitute."""
    items = [_normalize_line_item(item) for item in line_items]
    target_id = unavailable.get("item_id")
    for item in items:
        same_id = target_id and str(item.get("item_id")) == str(target_id)
        same_product = (
            unavailable.get("item_name")
            and _names_similar(item.get("item_name", ""), unavailable.get("item_name", ""))
            and (
                not unavailable.get("brand")
                or (item.get("brand") or "").lower() == str(unavailable.get("brand", "")).lower()
            )
        )
        if same_id or same_product:
            item["resolved"] = False
            item["item_id"] = None
            item["catalog_status"] = "stockout_pending"
    return items


async def _stockout_section_for_item(
    deps: NodeDependencies,
    db_session: Any,
    unavailable: dict[str, Any],
    *,
    cross_sell_rows: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str]:
    cross_sell_rows = list(cross_sell_rows or [])
    if cross_sell_rows and unavailable.get("item_id"):
        cross_sell_rows = [
            row
            for row in cross_sell_rows
            if str(row.get("source_item_id", "")) == str(unavailable["item_id"])
        ]
    if not cross_sell_rows and unavailable.get("item_id"):
        cross_sell_rows = await deps.cross_sell_lookup_tool.for_item(db_session, unavailable["item_id"])

    alternatives: list[dict[str, Any]] = []
    if cross_sell_rows:
        target_ids = cross_sell_rows[0].get("target_item_ids", [])
        for target_item_id in target_ids:
            details = await deps.catalog_service.get_item_by_id(db_session, str(target_item_id))
            if details and int(details.get("available_qty", 0)) > 0 and not is_expired(details.get("expiry_date")):
                alternatives.append(
                    {
                        "item_id": details["item_id"],
                        "name": details["name"],
                        "brand": details["brand"],
                        "weight_per_unit": details.get("weight_per_unit"),
                        "expiry_date": details.get("expiry_date"),
                        "price_paise": int(details["price_paise"]),
                        "available_qty": int(details["available_qty"]),
                    }
                )

    alternatives_source = "cross_sell_preference" if alternatives else "none"
    if not alternatives:
        same_name = await deps.catalog_service.find_alternatives(
            db_session,
            item_name=str(unavailable.get("item_name", "")),
            excluded_brand=unavailable.get("brand", ""),
            limit=3,
        )
        alternatives = [alt.model_dump() for alt in same_name]
        alternatives_source = "same_name_fallback" if alternatives else "none"

    alternatives_text = "\n".join(
        (
            f"- {alt.get('brand', '').strip()} {alt.get('name', '').strip()} | "
            f"{format_price_per_unit(alt.get('price_paise'), alt.get('weight_per_unit'))} | "
            f"{format_stock_qty(alt.get('available_qty'), alt.get('weight_per_unit'))}"
            + (f" | {format_expiry(alt.get('expiry_date'))}" if alt.get("expiry_date") else "")
        )
        for alt in alternatives[:3]
    ) or "- No alternatives currently in stock."

    section = OUT_OF_STOCK_WARNING_TEMPLATE.format(
        brand=unavailable.get("brand", ""),
        item=unavailable.get("item_name", ""),
        alternatives=alternatives_text,
    )
    return section, alternatives, cross_sell_rows, alternatives_source


async def suggest_alternative(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    unavailable_items = unavailable_items_from_state(state)
    if not unavailable_items:
        return {}
    async with deps.session_factory() as db_session:
        sections: list[str] = []
        all_alternatives: list[dict[str, Any]] = []
        all_cross_sell: list[dict[str, Any]] = []
        line_items = [_normalize_line_item(item) for item in state.get("line_items", [])]

        for unavailable in unavailable_items:
            section, alternatives, cross_sell_rows, alternatives_source = await _stockout_section_for_item(
                deps,
                db_session,
                unavailable,
            )
            sections.append(section)
            all_alternatives.extend(alternatives)
            all_cross_sell.extend(cross_sell_rows)
            line_items = _mark_line_stockout_pending(line_items, unavailable)

            creative_promo = await generate_creative_promo(
                deps.llm,
                unavailable_item_name=str(unavailable.get("item_name", "")),
                alternatives=alternatives,
            )
            creative_promo_source = "stub_fallback" if creative_promo.strip() == STUB_PROMO_TEXT else "llm"
            if creative_promo.strip():
                sections[-1] = f"{sections[-1].rstrip()}\n\n{creative_promo.strip()}"

            await deps.memory_store.append_audit(
                db_session,
                session_id=state["session_id"],
                actor="merchant_agent",
                action="ITEM_UNAVAILABLE",
                detail={
                    "requested": unavailable,
                    "alternatives": alternatives,
                    "alternatives_source": alternatives_source,
                    "cross_sell_candidates": cross_sell_rows,
                    "creative_promo": creative_promo,
                    "creative_promo_source": creative_promo_source,
                    "campaign_context": state.get("campaign_context", []),
                },
            )

        await db_session.commit()

    deduped_alternatives: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for alt in all_alternatives:
        alt_id = str(alt.get("item_id") or "")
        if alt_id and alt_id in seen_ids:
            continue
        if alt_id:
            seen_ids.add(alt_id)
        deduped_alternatives.append(alt)

    reply = "\n\n".join(section for section in sections if section)
    if len(unavailable_items) > 1:
        reply = (
            "⚠️ Multiple items need substitutes before this order can proceed:\n\n" + reply
        )

    surfaced_offers = await _offers_for_item_ids(
        deps,
        [str(alt.get("item_id")) for alt in deduped_alternatives if alt.get("item_id")],
    )
    promotions_block = format_surfaced_promotions(surfaced_offers, state.get("campaign_context") or [])
    if promotions_block:
        reply = f"{reply}\n\n{promotions_block}"

    return {
        "reply": reply,
        "catalog_suggestions": deduped_alternatives[:6],
        "cross_sell_candidates": all_cross_sell,
        "line_items": line_items,
        "unavailable_items": [],
        "unavailable_item": None,
        "resolved_offers": surfaced_offers,
        "status": "AWAITING_FIELDS",
    }


def _orderable_line_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Catalog-confirmed lines that can be reserved / invoiced."""
    return [
        _normalize_line_item(item)
        for item in state.get("line_items", [])
        if item.get("resolved")
        and item.get("item_id")
        and item.get("qty") is not None
        and item.get("catalog_status") != "stockout_pending"
    ]


def _blocking_unresolved_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Unresolved lines that must be fixed before invoice (excludes not_found)."""
    orderable = _orderable_line_items(state)
    blocking: list[dict[str, Any]] = []
    for item in state.get("line_items", []):
        if item.get("resolved"):
            continue
        if item.get("catalog_status") == "not_found":
            continue  # informed + dropped from order; do not block invoice
        if item.get("catalog_status") == "stockout_pending":
            continue  # surfaced via stockout reply; shopper must pick substitute
        if item.get("catalog_status") == "ambiguous" and orderable:
            continue  # invoice confirmed lines; ambiguous extras stay optional
        blocking.append(item)
    return blocking


def _compute_missing_fields(state: dict[str, Any]) -> list[str]:
    """Only ask for fields that are truly unknown — never re-ask cleared values."""
    missing: list[str] = []
    line_items = state.get("line_items", [])
    orderable = _orderable_line_items(state)
    stockout_pending = [
        item for item in line_items if item.get("catalog_status") == "stockout_pending"
    ]

    if stockout_pending:
        missing.append("In-stock alternative for out-of-stock item(s)")
    elif not line_items:
        missing.extend(["Exact product name + brand (per item)", "Quantity (per item)"])
    elif orderable:
        # At least one brand+name+qty line is confirmed — never re-ask product/brand warning.
        # Extra not_found / ambiguous lines are handled in reply sections, not this bullet.
        needs_qty = any(
            item.get("resolved") and item.get("qty") is None for item in line_items
        )
        if needs_qty:
            missing.append("Quantity (per item)")
    else:
        # No confirmed catalog line yet — collect product identity / qty for pending lines.
        needs_product = False
        needs_qty = False
        for item in line_items:
            has_name = bool(item.get("item_name"))
            has_brand = bool(item.get("brand"))
            has_qty = item.get("qty") is not None
            catalog_status = item.get("catalog_status")

            if catalog_status == "not_found":
                continue

            if has_name and has_brand:
                pass
            else:
                needs_product = True

            if not has_qty:
                needs_qty = True

        if needs_product or not any(
            item.get("catalog_status") != "not_found" for item in line_items
        ):
            missing.append("Exact product name + brand (per item)")
        if needs_qty:
            missing.append("Quantity (per item)")

    if not state.get("address"):
        missing.append("Delivery address")
    if not state.get("phone"):
        missing.append("Mobile number")
    if not state.get("customer_name"):
        missing.append("Customer name")
    if not state.get("mandate_verified", False):
        missing.append("Verified Human Sign Mandate")
    return _dedupe_missing_fields(missing)


def _format_known_summary(state: dict[str, Any]) -> str:
    """Only successfully confirmed catalog lines — never list not_found items here."""
    parts: list[str] = []
    for item in state.get("line_items") or []:
        if item.get("catalog_status") == "not_found":
            continue
        if not item.get("resolved"):
            continue  # pending / ambiguous shown via suggestions, not Already noted
        bit = item.get("item_name") or "item"
        if item.get("brand"):
            bit = f"{item['brand']} {bit}"
        if item.get("qty") is not None:
            bit = f"{bit} x{item['qty']}"
        parts.append(f"{bit} (confirmed)")
    if state.get("customer_name"):
        parts.append(f"customer={state['customer_name']}")
    if state.get("phone"):
        parts.append(f"phone={state['phone']}")
    if state.get("address"):
        parts.append(f"address={state['address']}")
    if not parts:
        return ""
    return "Already noted: " + "; ".join(parts) + "."


def _format_suggestion_line(suggestion: dict[str, Any]) -> str:
    name = suggestion.get("name")
    brand = suggestion.get("brand")
    qty = suggestion.get("available_qty")
    weight_per_unit = suggestion.get("weight_per_unit")
    price = suggestion.get("price_paise")
    expiry = suggestion.get("expiry_date")
    stock_txt = format_stock_qty(qty, weight_per_unit)
    price_txt = format_price_per_unit(price, weight_per_unit)
    expiry_txt = format_expiry(expiry)
    suffix = f" · {expiry_txt}" if expiry_txt else ""
    return f"• {brand} {name} — {stock_txt} · ({price_txt}){suffix}"


def _suggestion_matches_line_item(suggestion: dict[str, Any], line_item: dict[str, Any]) -> bool:
    item_name = str(line_item.get("item_name") or "")
    if not item_name:
        return False
    if _names_similar(str(suggestion.get("name", "")), item_name):
        return True
    if line_item.get("brand"):
        full = f"{line_item['brand']} {item_name}".strip()
        return _names_similar(f"{suggestion.get('brand', '')} {suggestion.get('name', '')}", full)
    return False


def _format_suggestions(
    suggestions: list[dict[str, Any]],
    *,
    line_items: list[dict[str, Any]] | None = None,
) -> str:
    if not suggestions:
        return ""

    def sort_key(suggestion: dict[str, Any]) -> tuple[int, str]:
        return (-int(suggestion.get("available_qty") or 0), str(suggestion.get("brand", "")).lower())

    lines = ["Catalog options:"]
    ambiguous_items = [
        item
        for item in (line_items or [])
        if not item.get("resolved") and item.get("catalog_status") == "ambiguous"
    ]
    shown_ids: set[str] = set()

    if ambiguous_items:
        for item in ambiguous_items:
            matched = [
                suggestion
                for suggestion in suggestions
                if str(suggestion.get("item_id")) not in shown_ids
                and _suggestion_matches_line_item(suggestion, item)
            ]
            matched.sort(key=sort_key)
            for suggestion in matched:
                item_id = str(suggestion.get("item_id"))
                if item_id:
                    shown_ids.add(item_id)
                lines.append(_format_suggestion_line(suggestion))

    for suggestion in sorted(suggestions, key=sort_key):
        item_id = str(suggestion.get("item_id"))
        if item_id and item_id in shown_ids:
            continue
        if item_id:
            shown_ids.add(item_id)
        lines.append(_format_suggestion_line(suggestion))

    lines.append("")
    lines.append("Reply with: Brand + product name, and quantity if not 1 (e.g. FreshFarm Beans, qty 2).")
    return "\n".join(lines)


def _format_not_in_catalog(state: dict[str, Any]) -> str:
    products: list[str] = []
    for item in state.get("line_items") or []:
        if item.get("resolved"):
            continue
        if item.get("catalog_status") != "not_found":
            continue
        product = item.get("item_name") or "unknown item"
        if item.get("brand"):
            product = f"{item['brand']} {product}"
        products.append(product)
    if not products:
        return ""
    bullets = "\n".join(f"- {product}" for product in products)
    return NOT_IN_CATALOG_TEMPLATE.format(product_bullets=bullets).strip()


def _format_stockout_pending(state: dict[str, Any]) -> str:
    pending: list[str] = []
    for item in state.get("line_items") or []:
        if item.get("catalog_status") != "stockout_pending":
            continue
        label = item.get("item_name") or "item"
        if item.get("brand"):
            label = f"{item['brand']} {label}"
        pending.append(label)
    if not pending:
        return ""
    items = ", ".join(pending)
    return (
        f"⚠️ Still waiting on a substitute for: {items}. "
        "Reply with in-stock substitutes for each item in one message "
        "(e.g. FreshFarm Beans qty 2, DairyGold Milk qty 1)."
    )


def _format_missing_warning(missing_fields: list[str]) -> str:
    if not missing_fields:
        return ""
    bullets = "\n".join(f"- {field}" for field in missing_fields)
    return MISSING_FIELDS_WARNING_TEMPLATE.format(missing_field_bullets=bullets).strip()


async def check_missing_fields(state: dict[str, Any], _deps: NodeDependencies) -> dict[str, Any]:
    missing_fields = _compute_missing_fields(state)
    blocking = _blocking_unresolved_items(state)
    if missing_fields or blocking:
        return {"missing_fields": missing_fields, "status": "AWAITING_FIELDS"}
    # Ready to invoice using only catalog-confirmed lines.
    return {
        "missing_fields": [],
        "status": "VALIDATED",
        "line_items": _orderable_line_items(state) or state.get("line_items", []),
    }


async def ask_for_fields(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    missing_fields = state.get("missing_fields", [])
    sections: list[str] = []

    known = _format_known_summary(state)
    if known:
        sections.append(known)

    not_in_catalog = _format_not_in_catalog(state)
    if not_in_catalog:
        sections.append(not_in_catalog)

    stockout_pending = _format_stockout_pending(state)
    if stockout_pending:
        sections.append(stockout_pending)

    has_stockout_pending = any(
        item.get("catalog_status") == "stockout_pending" for item in state.get("line_items") or []
    )
    has_orderable = bool(_orderable_line_items(state))
    suggestions = (
        []
        if has_stockout_pending or (has_orderable and not missing_fields)
        else (state.get("catalog_suggestions") or [])
    )
    suggestion_block = _format_suggestions(suggestions, line_items=state.get("line_items") or [])
    if suggestion_block:
        sections.append(suggestion_block)
    else:
        ambiguous = [
            f"{(item.get('brand') + ' ') if item.get('brand') else ''}{item.get('item_name')}"
            for item in state.get("line_items") or []
            if not item.get("resolved") and item.get("catalog_status") == "ambiguous"
        ]
        if ambiguous:
            sections.append(
                "Multiple catalog matches for: "
                + ", ".join(ambiguous)
                + ". Please reply with exact brand + product name."
            )

    promo_offers = list(state.get("resolved_offers") or [])
    if not promo_offers and suggestions:
        suggestion_ids = [str(suggestion.get("item_id")) for suggestion in suggestions if suggestion.get("item_id")]
        promo_offers = await _offers_for_item_ids(deps, suggestion_ids)
    promotions_block = format_surfaced_promotions(promo_offers, state.get("campaign_context") or [])
    if promotions_block:
        sections.append(promotions_block)

    # Catalog options already ask for brand+product — don't repeat that bullet in the warning.
    warning_fields = list(missing_fields)
    if suggestion_block:
        warning_fields = [
            field
            for field in warning_fields
            if field != "Exact product name + brand (per item)"
        ]

    warning_block = _format_missing_warning(warning_fields)
    if warning_block:
        sections.append(warning_block)
    elif not not_in_catalog and not suggestion_block:
        # Unresolved identity but nothing else missing (e.g. waiting on brand pick).
        sections.append(
            "⚠️ Warning: Please confirm a catalog product (name + brand) before I can proceed for invoice creation process."
        )

    reply = "\n\n".join(section for section in sections if section)

    async with deps.session_factory() as db_session:
        await deps.memory_store.append_audit(
            db_session,
            session_id=state["session_id"],
            actor="merchant_agent",
            action="FIELDS_STILL_MISSING",
            detail={
                "missing_fields": missing_fields,
                "known_line_items": state.get("line_items", []),
                "suggestion_count": len(suggestions),
                "not_in_catalog": [
                    item.get("item_name")
                    for item in state.get("line_items") or []
                    if item.get("catalog_status") == "not_found"
                ],
            },
        )
        await db_session.commit()

    return {"reply": reply, "status": "AWAITING_FIELDS"}


async def finalize_order(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    line_items = _orderable_line_items(state)
    if not line_items:
        return {
            "status": "AWAITING_FIELDS",
            "missing_fields": ["Exact product name + brand (per item)"],
            "reply": "No catalog-confirmed items are ready to invoice yet.",
        }
    reservation_invoice_id = state.get("reservation_invoice_id") or str(uuid4())
    unavailable_items: list[dict[str, Any]] = []
    async with deps.session_factory() as db_session:
        for item in line_items:
            latest = await deps.catalog_service.get_item_by_id(db_session, item["item_id"])
            if (
                not latest
                or is_expired(latest.get("expiry_date"))
                or int(latest["available_qty"]) < int(item["qty"])
            ):
                unavailable_items.append(
                    {
                        "item_id": item["item_id"],
                        "item_name": item["item_name"],
                        "brand": item["brand"],
                        "requested_qty": item["qty"],
                        "available_qty": (latest or {}).get("available_qty", 0),
                        "weight_per_unit": (latest or {}).get("weight_per_unit"),
                        "expiry_date": (latest or {}).get("expiry_date"),
                    }
                )
                continue
            item["available_qty"] = latest["available_qty"]
            item["unit_price_paise"] = latest["price_paise"]
            item["weight_per_unit"] = latest.get("weight_per_unit")
            item["expiry_date"] = latest.get("expiry_date")

        if unavailable_items:
            return {
                "status": "AWAITING_FIELDS",
                "unavailable_items": unavailable_items,
                "unavailable_item": unavailable_items[0],
                "reservation_invoice_id": reservation_invoice_id,
            }

        await deps.memory_store.append_audit(
            db_session,
            session_id=state["session_id"],
            actor="merchant_agent",
            action="ORDER_VALIDATED",
            detail={"line_items": line_items},
        )
        await db_session.commit()

    return {
        "line_items": line_items,
        "status": "VALIDATED",
        "reply": "Order validated. Generating invoice now.",
        "unavailable_item": None,
        "reservation_invoice_id": reservation_invoice_id,
    }


async def generate_invoice(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    accepted_offers = _build_accepted_offers(state)
    reservation_invoice_id = state.get("reservation_invoice_id")
    async with deps.session_factory() as db_session:
        invoice = await deps.invoice_service.generate_invoice(
            db_session,
            session_id=state["session_id"],
            consumer_agent_id=state["consumer_agent_id"],
            mandate_verified=bool(state.get("mandate_verified", False)),
            line_items=state.get("line_items", []),
            customer_name=state.get("customer_name"),
            address=state.get("address"),
            phone=state.get("phone"),
            accepted_offers=accepted_offers,
            order_id=reservation_invoice_id,
        )
        await deps.memory_store.append_audit(
            db_session,
            session_id=state["session_id"],
            actor="merchant_agent",
            action="OFFER_APPLIED_LOGGED",
            detail={"accepted_offers": accepted_offers},
        )
        await db_session.commit()

    return {
        "invoice": invoice.model_dump(),
        "status": "VALIDATED",
        "reply": "Invoice generated. Dispatching reservation and payment link.",
        "awaiting_invoice_confirmation": False,
        "invoice_proceed": False,
    }


def _normalize_exception_result(exc: BaseException) -> dict[str, Any]:
    return {"success": False, "error": {"code": "UPSTREAM_EXCEPTION", "message": str(exc)}}


def _result_or_exception(result: Any) -> dict[str, Any]:
    if isinstance(result, BaseException):
        return _normalize_exception_result(result)
    if isinstance(result, dict):
        if result.get("success") is False:
            err = result.get("error")
            if isinstance(err, str):
                result["error"] = {"code": "UPSTREAM_ERROR", "message": err}
            elif not isinstance(err, dict):
                result["error"] = {"code": "UPSTREAM_ERROR", "message": "Unknown upstream error"}
        return result
    return {"success": False, "error": {"code": "UNEXPECTED_RESPONSE", "message": "Unexpected response"}}


def _resolve_merchant_id(state: dict[str, Any]) -> str:
    settings = get_settings()
    state_mid = str(state.get("merchant_id") or "").strip()
    default_mid = str(settings.default_merchant_id or "").strip()
    return state_mid or default_mid or "00000000-0000-0000-0000-000000000001"


def _payment_expiry_iso() -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(settings.payment_link_ttl_seconds))
    return expires_at.isoformat()


async def dispatch_invoice_processing(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    invoice = dict(state.get("invoice") or {})
    if not invoice:
        return {"reservation_result": {"success": False, "error": "Missing invoice payload"}, "payment_result": None}
    if deps.reservation_client is None or deps.payment_client is None:
        return {
            "reservation_result": {"success": False, "error": "Reservation/payment clients are not configured"},
            "payment_result": {"success": False, "error": "Reservation/payment clients are not configured"},
        }

    invoice_id = str(invoice.get("order_id") or state.get("reservation_invoice_id") or "")
    line_items = list(invoice.get("line_items") or [])
    merchant_id = _resolve_merchant_id(state)
    description = f"Invoice {invoice_id} payment"
    customer_name = state.get("customer_name") or invoice.get("customer_name")
    phone = state.get("phone") or invoice.get("phone_number")

    reservation_task = deps.reservation_client.submit_invoice(
        {
            "invoice_id": invoice_id,
            "line_items": line_items,
            "invoice": invoice,
        }
    )
    payment_task = deps.payment_client.create_payment_link(
        merchant_id=merchant_id,
        session_id=state.get("session_id"),
        invoice_id=invoice_id,
        amount_paise=int(invoice.get("total_paise") or 0),
        customer_name=customer_name,
        phone=phone,
        description=description,
    )

    reservation_raw, payment_raw = await asyncio.gather(
        reservation_task,
        payment_task,
        return_exceptions=True,
    )
    return {
        "reservation_result": _result_or_exception(reservation_raw),
        "payment_result": _result_or_exception(payment_raw),
    }


async def resolve_invoice_outcome(state: dict[str, Any], deps: NodeDependencies) -> dict[str, Any]:
    invoice = dict(state.get("invoice") or {})
    reservation_result = dict(state.get("reservation_result") or {})
    payment_result = dict(state.get("payment_result") or {})
    reservation_ok = bool(reservation_result.get("success"))
    payment_ok = bool(payment_result.get("success"))
    invoice_id = str(invoice.get("order_id") or state.get("reservation_invoice_id") or "")

    updates: dict[str, Any] = {
        "invoice": invoice,
        "reservation_result": reservation_result,
        "payment_result": payment_result,
        "reservation_invoice_id": invoice_id or state.get("reservation_invoice_id"),
    }
    merchant_id = _resolve_merchant_id(state)
    payment_link_url = payment_result.get("payment_link_url") if payment_ok else None
    payment_expires_at = str(payment_result.get("expires_at") or "") if payment_ok else ""
    if payment_ok and not payment_expires_at:
        payment_expires_at = _payment_expiry_iso()
    reservation_expires_at = (
        str(reservation_result.get("expires_at") or "")
        if reservation_ok
        else ""
    )

    if reservation_ok and payment_ok:
        if payment_link_url:
            invoice["payment_link_url"] = payment_link_url
        if payment_expires_at:
            invoice["payment_expires_at"] = payment_expires_at
        if reservation_expires_at:
            invoice["reservation_expires_at"] = reservation_expires_at
        updates.update(
            {
                "status": "INVOICED",
                "reply": (
                    "Invoice generated successfully.\n"
                    f"Total: {format_inr_paise(int(invoice.get('total_paise') or 0))}\n"
                    f"Payment link: {payment_link_url}\n"
                    + (f"Pay before: {payment_expires_at}\n" if payment_expires_at else "")
                    + (f"Reservation hold until: {reservation_expires_at}" if reservation_expires_at else "")
                ).strip(),
                "payment_link_url": payment_link_url,
                "payment_expires_at": payment_expires_at or None,
                "reservation_expires_at": reservation_expires_at or None,
                "awaiting_invoice_confirmation": False,
                "invoice_proceed": False,
                "unavailable_items": [],
                "unavailable_item": None,
            }
        )
        audit_action = "INVOICE_FULFILLED"
        audit_detail = {
            "invoice_id": invoice_id,
            "reservation_result": reservation_result,
            "payment_result": payment_result,
        }
    elif reservation_ok and not payment_ok:
        if reservation_expires_at:
            invoice["reservation_expires_at"] = reservation_expires_at
        updates.update(
            {
                "status": "INVOICED",
                "reply": (
                    "Invoice created, but payment link generation failed.\n"
                    + (f"Reservation is held until {reservation_expires_at}.\n" if reservation_expires_at else "")
                    + "Please retry payment link creation."
                ).strip(),
                "reservation_expires_at": reservation_expires_at or None,
                "payment_link_url": None,
                "payment_expires_at": None,
                "awaiting_invoice_confirmation": False,
                "invoice_proceed": False,
            }
        )
        audit_action = "PAYMENT_LINK_FAILED"
        audit_detail = {
            "invoice_id": invoice_id,
            "reservation_result": reservation_result,
            "payment_result": payment_result,
        }
    elif not reservation_ok and payment_ok:
        if deps.payment_client is not None and invoice_id:
            try:
                await deps.payment_client.cancel_payment_link(merchant_id=merchant_id, invoice_id=invoice_id)
            except Exception as exc:
                async with deps.session_factory() as db_session:
                    await deps.memory_store.append_audit(
                        db_session,
                        session_id=state["session_id"],
                        actor="merchant_agent",
                        action="ORPHANED_PAYMENT_LINK_RISK",
                        detail={
                            "invoice_id": invoice_id,
                            "merchant_id": merchant_id,
                            "cancel_error": str(exc),
                            "payment_result": payment_result,
                        },
                    )
                    await db_session.commit()
        unavailable_items = reservation_result.get("unavailable_items")
        if not isinstance(unavailable_items, list):
            unavailable_items = []
        updates.update(
            {
                "status": "AWAITING_FIELDS",
                "reply": "Some items became unavailable, so payment link was voided. Please pick alternatives.",
                "unavailable_items": unavailable_items,
                "unavailable_item": unavailable_items[0] if unavailable_items else None,
                "payment_link_url": None,
                "payment_expires_at": None,
                "reservation_expires_at": None,
                "invoice": None,
                "awaiting_invoice_confirmation": False,
                "invoice_proceed": False,
            }
        )
        audit_action = "RESERVATION_FAILED_PAYMENT_VOIDED"
        audit_detail = {
            "invoice_id": invoice_id,
            "reservation_result": reservation_result,
            "payment_result": payment_result,
        }
    else:
        unavailable_items = reservation_result.get("unavailable_items")
        if not isinstance(unavailable_items, list):
            unavailable_items = []
        updates.update(
            {
                "status": "AWAITING_FIELDS",
                "reply": "Unable to finalize invoice because reservation failed. Please choose available alternatives.",
                "unavailable_items": unavailable_items,
                "unavailable_item": unavailable_items[0] if unavailable_items else None,
                "payment_link_url": None,
                "payment_expires_at": None,
                "reservation_expires_at": None,
                "invoice": None,
                "awaiting_invoice_confirmation": False,
                "invoice_proceed": False,
            }
        )
        audit_action = "RESERVATION_FAILED"
        audit_detail = {
            "invoice_id": invoice_id,
            "reservation_result": reservation_result,
            "payment_result": payment_result,
        }

    async with deps.session_factory() as db_session:
        await deps.memory_store.append_audit(
            db_session,
            session_id=state["session_id"],
            actor="merchant_agent",
            action=audit_action,
            detail=audit_detail,
        )
        await db_session.commit()

    return updates
