from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from services.merchant_agent.graph.nodes import (
    NodeDependencies,
    _apply_substitute_phrase,
    _apply_default_qty,
    _compute_missing_fields,
    _detect_removed_item_names,
    _mark_line_stockout_pending,
    _blocking_unresolved_items,
    _format_suggestions,
    _orderable_line_items,
    ask_for_fields,
    check_availability,
    check_missing_fields,
    generate_invoice,
    off_topic_guard,
    offer_invoice_confirmation,
    parse_intent,
    resolve_invoice_confirmation,
    suggest_alternative,
)
from services.merchant_agent.invoice_service import InvoiceService
from services.merchant_agent.memory_store import MemoryStore
from services.merchant_agent.persona import OUT_OF_STOCK_WARNING_TEMPLATE
from shared.llm_client import FakeChatModel


class FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.committed = False

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@dataclass
class FakeCatalogService:
    alternatives: list[dict[str, Any]]
    stock_by_id: dict[str, int] | None = None

    async def find_alternatives(self, *_args, **_kwargs):
        return [type("Alt", (), {**alt, "model_dump": lambda self_alt, a=alt: a})() for alt in self.alternatives]

    async def get_item_by_id(self, _db_session, item_id: str) -> dict[str, Any] | None:
        stock = (self.stock_by_id or {}).get(item_id)
        if stock is None:
            return None
        return {
            "item_id": item_id,
            "name": "Beans" if "bean" in item_id else "Milk",
            "brand": "Brand",
            "weight_per_unit": "kg" if "bean" in item_id else "L",
            "expiry_date": "2026-12-31",
            "price_paise": 1000,
            "available_qty": stock,
        }


class FakeMemoryStore:
    def __init__(self) -> None:
        self.audit_events: list[dict[str, Any]] = []
        self.saved_states: list[dict[str, Any]] = []

    async def load_state(self, _session_id: str) -> dict[str, Any] | None:
        return None

    async def load_order_draft(self, _session_id: str) -> dict[str, Any] | None:
        return None

    async def save_state(self, _session_id: str, state: dict[str, Any]) -> None:
        self.saved_states.append(state)

    async def append_audit(self, _db_session, *, session_id: str, actor: str, action: str, detail: dict[str, Any]) -> None:
        self.audit_events.append(
            {
                "session_id": session_id,
                "actor": actor,
                "action": action,
                "detail": detail,
            }
        )


class FakePersonalMemoryStore:
    async def list_by_consumer(self, _db_session, *, consumer_agent_id: str) -> dict[str, dict[str, Any]]:
        return {"customer_profile": {"consumer_agent_id": consumer_agent_id}}


class FakeCrossSellLookupTool:
    async def for_item(self, _db_session, _item_id: str) -> list[dict[str, Any]]:
        return []


def _deps(
    *,
    llm_response: str = "{}",
    memory_store: FakeMemoryStore | None = None,
    alternatives: list[dict[str, Any]] | None = None,
) -> NodeDependencies:
    memory = memory_store or FakeMemoryStore()
    session = FakeSession()
    return NodeDependencies(
        llm=FakeChatModel(canned_response=llm_response),
        session_factory=lambda: FakeSessionFactory(session),
        catalog_service=FakeCatalogService(alternatives=alternatives or []),  # type: ignore[arg-type]
        memory_store=memory,  # type: ignore[arg-type]
        invoice_service=InvoiceService(memory_store=memory),  # type: ignore[arg-type]
        personal_memory_store=FakePersonalMemoryStore(),  # type: ignore[arg-type]
        reservation_client=None,
        payment_client=None,
        offer_lookup_tool=None,
        cross_sell_lookup_tool=FakeCrossSellLookupTool(),
        campaign_orchestrator_scan_tool=None,
    )


def test_format_suggestions_shows_all_ambiguous_products_not_capped_at_five() -> None:
    suggestions = [
        {"item_id": "b1", "name": "Beans", "brand": "FreshFarm", "available_qty": 8, "weight_per_unit": "kg", "price_paise": 14500, "expiry_date": "2026-12-31"},
        {"item_id": "b2", "name": "Beans", "brand": "HomeSelect", "available_qty": 0, "weight_per_unit": "kg", "price_paise": 13800, "expiry_date": "2026-12-31"},
        {"item_id": "b3", "name": "Kidney Beans", "brand": "24 Mantra", "available_qty": 5, "weight_per_unit": "g", "price_paise": 12900, "expiry_date": "2026-12-31"},
        {"item_id": "b4", "name": "Kidney Beans", "brand": "Tata Sampann", "available_qty": 7, "weight_per_unit": "g", "price_paise": 11500, "expiry_date": "2026-12-31"},
        {"item_id": "m1", "name": "Milk", "brand": "Amul", "available_qty": 0, "weight_per_unit": "L", "price_paise": 6500, "expiry_date": "2026-12-31"},
        {"item_id": "m2", "name": "Milk", "brand": "DairyGold", "available_qty": 25, "weight_per_unit": "L", "price_paise": 6200, "expiry_date": "2026-12-31"},
    ]
    line_items = [
        {"item_name": "beans", "resolved": False, "catalog_status": "ambiguous"},
        {"item_name": "milk", "resolved": False, "catalog_status": "ambiguous"},
    ]
    block = _format_suggestions(suggestions, line_items=line_items)
    assert "DairyGold Milk" in block
    assert "Amul Milk" in block
    assert "FreshFarm Beans" in block


@pytest.mark.asyncio
async def test_offer_invoice_confirmation_prompts_before_invoice() -> None:
    memory = FakeMemoryStore()
    deps = _deps(memory_store=memory)
    state = {
        "session_id": "s-confirm",
        "line_items": [
            {
                "item_name": "Milk",
                "brand": "Amul",
                "qty": 1,
                "item_id": "m1",
                "resolved": True,
                "catalog_status": "resolved",
            }
        ],
        "customer_name": "Ananya",
        "phone": "+91 98231 45678",
        "address": "Pune",
        "resolved_offers": [
            {
                "id": "f1",
                "offer_type": "FESTIVAL_CAMPAIGN",
                "name": "Monsoon Pantry Festival",
                "description": "5% cashback on Amul Milk and Fortune Rice basket.",
                "discount_type": "CASHBACK",
                "value": 5,
                "festival_name": "Monsoon Specials",
            }
        ],
    }
    updates = await offer_invoice_confirmation(state, deps)
    assert updates["status"] == "AWAITING_CONFIRMATION"
    assert updates["awaiting_invoice_confirmation"] is True
    assert "All required order details are collected" in updates["reply"]
    assert "Proceed" in updates["reply"]
    assert "Promotions & deals" in updates["reply"]
    assert memory.audit_events[-1]["action"] == "INVOICE_CONFIRMATION_OFFERED"


@pytest.mark.asyncio
async def test_resolve_invoice_confirmation_proceed_flag() -> None:
    updates = await resolve_invoice_confirmation(
        {"awaiting_invoice_confirmation": True, "message": "Yes, proceed with invoice creation"},
        _deps(),
    )
    assert updates["invoice_proceed"] is True
    assert updates["awaiting_invoice_confirmation"] is False


@pytest.mark.asyncio
async def test_check_missing_fields_validates_when_ambiguous_extra_and_customer_complete() -> None:
    state = {
        "line_items": [
            {
                "item_name": "Milk",
                "brand": "Amul",
                "qty": 1,
                "item_id": "m1",
                "resolved": True,
                "catalog_status": "resolved",
            },
            {"item_name": "Beans", "brand": None, "qty": None, "resolved": False, "catalog_status": "ambiguous"},
        ],
        "mandate_verified": True,
        "customer_name": "Ananya Deshmukh",
        "phone": "+91 98231 45678",
        "address": "Flat 12B, Maple Heights, FC Road, Shivajinagar, Pune, Maharashtra, 411004",
    }
    updates = await check_missing_fields(state, _deps())
    assert updates["status"] == "VALIDATED"
    assert len(updates["line_items"]) == 1
    assert updates["line_items"][0]["brand"] == "Amul"
    assert _blocking_unresolved_items(state) == []


def test_apply_default_qty_sets_one_for_confirmed_product() -> None:
    items = _apply_default_qty(
        [
            {"item_name": "Milk", "brand": "Amul", "qty": None, "resolved": True, "item_id": "m1"},
            {"item_name": "Beans", "brand": "FreshFarm", "qty": 10, "resolved": True, "item_id": "b1"},
            {"item_name": "beans", "brand": None, "qty": None, "resolved": False},
        ]
    )
    assert items[0]["qty"] == 1
    assert items[1]["qty"] == 10
    assert items[2].get("qty") is None


def test_compute_missing_fields_omits_qty_when_default_applied() -> None:
    missing = _compute_missing_fields(
        {
            "line_items": [
                {
                    "item_name": "Milk",
                    "brand": "Amul",
                    "qty": 1,
                    "resolved": True,
                    "item_id": "m1",
                    "catalog_status": "resolved",
                }
            ],
            "mandate_verified": True,
            "customer_name": "A",
            "phone": "1",
            "address": "B",
        }
    )
    assert "Quantity (per item)" not in missing


def test_detect_removed_item_names_no_milk_required() -> None:
    assert "milk" in _detect_removed_item_names("FreshFarm Beans 4 , no milk required")
    assert "beans" in _detect_removed_item_names("don't want beans please")


@pytest.mark.asyncio
async def test_parse_intent_removes_cancelled_milk() -> None:
    canned = (
        '{"line_items":[{"item_name":"Beans","brand":"FreshFarm","qty":4}],'
        '"remove_item_names":["milk"],"customer_name":null,"address":null,"phone":null}'
    )
    deps = _deps(llm_response=canned)
    state = {
        "session_id": "s-cancel",
        "message": "FreshFarm Beans 4 , no milk required",
        "line_items": [
            {"item_name": "beans", "brand": None, "qty": None, "resolved": False},
            {"item_name": "milk", "brand": None, "qty": None, "resolved": False},
        ],
    }
    updates = await parse_intent(state, deps)
    names = [str(item.get("item_name") or "").lower() for item in updates["line_items"]]
    assert any("bean" in name for name in names)
    assert not any(name == "milk" or name.endswith("milk") for name in names)


@pytest.mark.asyncio
async def test_off_topic_guard_short_circuits() -> None:
    deps = _deps(llm_response='{"off_topic": true}')
    state = {"session_id": "s1", "message": "Tell me a joke", "mandate_verified": True}
    updates = await off_topic_guard(state, deps)
    assert updates["off_topic"] is True
    assert "I only handle order placement" in updates["reply"]


@pytest.mark.asyncio
async def test_missing_fields_warning_lists_only_missing() -> None:
    memory = FakeMemoryStore()
    deps = _deps(memory_store=memory)
    state = {
        "session_id": "s2",
        "line_items": [],
        "mandate_verified": True,
        "customer_name": None,
        "address": None,
        "phone": None,
        "catalog_suggestions": [],
    }
    missing = await check_missing_fields(state, deps)
    state.update(missing)
    updates = await ask_for_fields(state, deps)
    assert "Verified Human Sign Mandate" not in updates["reply"]
    assert "- Delivery address" in updates["reply"]
    assert "- Mobile number" in updates["reply"]
    assert "- Customer name" in updates["reply"]
    assert "- Exact product name + brand (per item)" in updates["reply"]
    assert memory.audit_events[-1]["action"] == "FIELDS_STILL_MISSING"


@pytest.mark.asyncio
async def test_not_in_catalog_message() -> None:
    memory = FakeMemoryStore()
    deps = _deps(memory_store=memory)
    state = {
        "session_id": "s-na",
        "line_items": [
            {"item_name": "Pepsi", "brand": None, "qty": 2, "resolved": False, "catalog_status": "not_found"},
            {
                "item_name": "Milk",
                "brand": "DairyGold",
                "qty": 10,
                "item_id": "m1",
                "resolved": True,
                "catalog_status": "resolved",
            },
        ],
        "mandate_verified": True,
        "customer_name": None,
        "address": None,
        "phone": None,
        "missing_fields": ["Delivery address", "Mobile number", "Customer name"],
        "catalog_suggestions": [],
    }
    updates = await ask_for_fields(state, deps)
    assert "⚠️ Not available in catalog:" in updates["reply"]
    assert "- Pepsi" in updates["reply"]
    assert "These items are excluded from the invoice" in updates["reply"]
    assert updates["reply"].count("⚠️ Not available in catalog:") == 1
    assert updates["reply"].count("These items are excluded from the invoice") == 1
    assert "Already noted: DairyGold Milk x10 (confirmed)" in updates["reply"]
    assert "Pepsi" not in updates["reply"].split("Not available in catalog:")[0]
    assert "Verified Human Sign Mandate" not in updates["reply"]
    assert "- Exact product name + brand (per item)" not in updates["reply"]
    assert "- Delivery address" in updates["reply"]


@pytest.mark.asyncio
async def test_not_in_catalog_lists_multiple_under_one_warning() -> None:
    memory = FakeMemoryStore()
    deps = _deps(memory_store=memory)
    state = {
        "session_id": "s-na-multi",
        "line_items": [
            {
                "item_name": "milk",
                "brand": "Goldy",
                "qty": 1,
                "resolved": False,
                "catalog_status": "not_found",
            },
            {
                "item_name": "chocolate",
                "brand": None,
                "qty": 1,
                "resolved": False,
                "catalog_status": "not_found",
            },
            {
                "item_name": "Beans",
                "brand": "FreshFarm",
                "qty": 4,
                "item_id": "b1",
                "resolved": True,
                "catalog_status": "resolved",
            },
        ],
        "mandate_verified": True,
        "customer_name": None,
        "address": None,
        "phone": None,
        "missing_fields": ["Delivery address", "Mobile number", "Customer name"],
        "catalog_suggestions": [],
    }
    updates = await ask_for_fields(state, deps)
    assert updates["reply"].count("⚠️ Not available in catalog:") == 1
    assert "- Goldy milk" in updates["reply"]
    assert "- chocolate" in updates["reply"]
    assert updates["reply"].count("These items are excluded from the invoice") == 1
    assert "This item is excluded from the invoice" not in updates["reply"]


@pytest.mark.asyncio
async def test_not_found_does_not_block_invoice_when_other_items_ready() -> None:
    state = {
        "line_items": [
            {
                "item_name": "Milk",
                "brand": "DairyGold",
                "qty": 10,
                "item_id": "m1",
                "resolved": True,
                "catalog_status": "resolved",
            },
            {
                "item_name": "chocolate",
                "brand": None,
                "qty": None,
                "resolved": False,
                "catalog_status": "not_found",
            },
        ],
        "customer_name": "Priya Mehta",
        "address": "Baner Road Pune",
        "phone": "+91 9123456789",
        "mandate_verified": True,
    }
    missing = _compute_missing_fields(state)
    assert missing == []
    assert "Exact product name + brand (per item)" not in missing
    checked = await check_missing_fields(state, _deps())
    assert checked["status"] == "VALIDATED"
    assert all(item.get("resolved") for item in checked["line_items"])
    assert all(item.get("item_name") != "chocolate" for item in checked["line_items"])


@pytest.mark.asyncio
async def test_missing_fields_does_not_reask_known_brand_qty() -> None:
    state = {
        "line_items": [
            {"item_name": "Milk", "brand": "DairyGold", "qty": 10, "resolved": False},
        ],
        "customer_name": None,
        "address": None,
        "phone": None,
        "mandate_verified": True,
        "catalog_suggestions": [
            {"item_id": "1", "name": "Milk", "brand": "DairyGold", "price_paise": 6200, "available_qty": 25},
        ],
    }
    missing = _compute_missing_fields(state)
    assert "Exact product name + brand (per item)" not in missing
    assert "Quantity (per item)" not in missing
    assert "Delivery address" in missing
    assert "Mobile number" in missing
    assert "Customer name" in missing


@pytest.mark.asyncio
async def test_confirmed_item_skips_product_brand_warning_even_with_extras() -> None:
    state = {
        "line_items": [
            {
                "item_name": "Milk",
                "brand": "DairyGold",
                "qty": 10,
                "item_id": "m1",
                "resolved": True,
                "catalog_status": "resolved",
            },
            {"item_name": "chocolate", "resolved": False, "catalog_status": "not_found"},
            {"item_name": "beans", "brand": None, "qty": None, "resolved": False, "catalog_status": "ambiguous"},
        ],
        "customer_name": None,
        "address": None,
        "phone": None,
        "mandate_verified": True,
    }
    missing = _compute_missing_fields(state)
    assert "Exact product name + brand (per item)" not in missing
    assert "Quantity (per item)" not in missing
    assert "Delivery address" in missing


@pytest.mark.asyncio
async def test_ask_for_fields_includes_known_summary_and_suggestions() -> None:
    memory = FakeMemoryStore()
    deps = _deps(memory_store=memory)
    state = {
        "session_id": "s-dyn",
        "line_items": [{"item_name": "Milk", "brand": "DairyGold", "qty": 10, "resolved": False}],
        "mandate_verified": True,
        "customer_name": None,
        "address": None,
        "phone": None,
        "missing_fields": ["Delivery address", "Mobile number", "Customer name"],
        "catalog_suggestions": [
            {"item_id": "1", "name": "Milk", "brand": "Amul", "price_paise": 6500, "available_qty": 1},
            {"item_id": "2", "name": "Milk", "brand": "DairyGold", "price_paise": 6200, "available_qty": 25},
        ],
    }
    updates = await ask_for_fields(state, deps)
    # Unresolved line may still appear in suggestions context, but Already noted needs confirmed identity.
    assert "Already noted:" in updates["reply"] or "Catalog options" in updates["reply"]
    assert "Catalog options:" in updates["reply"]
    assert "- Delivery address" in updates["reply"]
    assert "- Mobile number" in updates["reply"]
    assert "- Customer name" in updates["reply"]
    assert "Verified Human Sign Mandate" not in updates["reply"]
    assert "Exact product name + brand (per item)" not in updates["reply"]
    assert "Quantity (per item)" not in updates["reply"]


@pytest.mark.asyncio
async def test_ask_for_fields_shows_promotions_block() -> None:
    memory = FakeMemoryStore()
    deps = _deps(memory_store=memory)
    state = {
        "session_id": "s-promo",
        "line_items": [{"item_name": "Beans", "brand": None, "qty": None, "resolved": False}],
        "mandate_verified": True,
        "customer_name": None,
        "address": None,
        "phone": None,
        "missing_fields": ["Quantity (per item)", "Delivery address"],
        "resolved_offers": [
            {
                "id": "offer-1",
                "offer_type": "DISCOUNT",
                "name": "FreshFarm Beans Bulk Saver",
                "description": "Buy 2+ FreshFarm Beans packs and get 10% off.",
                "discount_type": "PERCENT",
                "value": 10,
            }
        ],
        "catalog_suggestions": [],
    }
    updates = await ask_for_fields(state, deps)
    assert "Promotions & deals you can unlock" in updates["reply"]
    assert "Buy 2+ FreshFarm Beans" in updates["reply"]


@pytest.mark.asyncio
async def test_ask_for_fields_hides_catalog_options_during_stockout() -> None:
    memory = FakeMemoryStore()
    deps = _deps(memory_store=memory)
    state = {
        "session_id": "s-stockout-fields",
        "line_items": [
            {
                "item_name": "Beans",
                "brand": "HomeSelect",
                "qty": 2,
                "resolved": False,
                "catalog_status": "stockout_pending",
            }
        ],
        "mandate_verified": True,
        "missing_fields": ["In-stock alternative for out-of-stock item(s)", "Delivery address"],
        "catalog_suggestions": [
            {
                "item_id": "kidney",
                "name": "Kidney Beans",
                "brand": "Tata Sampann",
                "price_paise": 11500,
                "available_qty": 7,
                "weight_per_unit": "g",
                "expiry_date": "2026-12-31",
            },
        ],
    }
    updates = await ask_for_fields(state, deps)
    assert "Catalog options:" not in updates["reply"]
    assert "Still waiting on a substitute" in updates["reply"]
    assert "Kidney Beans" not in updates["reply"]


@pytest.mark.asyncio
async def test_ask_for_fields_omits_product_bullet_when_catalog_options_shown() -> None:
    """Catalog options already ask for brand+product — warning must not repeat it."""
    memory = FakeMemoryStore()
    deps = _deps(memory_store=memory)
    state = {
        "session_id": "s-overlap",
        "line_items": [{"item_name": "beans", "brand": None, "qty": None, "resolved": False}],
        "mandate_verified": True,
        "customer_name": None,
        "address": None,
        "phone": None,
        "missing_fields": [
            "Exact product name + brand (per item)",
            "Quantity (per item)",
            "Delivery address",
            "Mobile number",
            "Customer name",
        ],
        "catalog_suggestions": [
            {
                "item_id": "b1",
                "name": "Beans",
                "brand": "FreshFarm",
                "price_paise": 14500,
                "available_qty": 8,
            },
        ],
    }
    updates = await ask_for_fields(state, deps)
    assert "Catalog options:" in updates["reply"]
    assert "Exact product name + brand (per item)" not in updates["reply"]
    assert "- Quantity (per item)" in updates["reply"]
    assert "- Delivery address" in updates["reply"]
    assert "⚠️ Still needed before proceeding towards the next process of invoice creation:" in updates["reply"]


@pytest.mark.asyncio
async def test_parse_intent_swaps_brand_for_same_product() -> None:
    canned = (
        '{"line_items":[{"item_name":"Beans","brand":"FreshFarm","qty":2}],'
        '"remove_item_names":[],"customer_name":null,"address":null,"phone":null}'
    )
    deps = _deps(llm_response=canned)
    state = {
        "session_id": "s-swap",
        "message": "Use FreshFarm Beans instead, qty 2",
        "line_items": [
            {
                "item_name": "Beans",
                "brand": "HomeSelect",
                "qty": 10,
                "resolved": False,
                "catalog_status": "stockout_pending",
            }
        ],
    }
    updates = await parse_intent(state, deps)
    assert len(updates["line_items"]) == 1
    assert updates["line_items"][0]["brand"] == "FreshFarm"
    assert updates["line_items"][0]["qty"] == 2
    assert updates["line_items"][0]["resolved"] is False


def test_mark_line_stockout_pending() -> None:
    items = _mark_line_stockout_pending(
        [
            {
                "item_name": "Beans",
                "brand": "HomeSelect",
                "item_id": "oos-1",
                "qty": 2,
                "resolved": True,
            }
        ],
        {"item_id": "oos-1", "item_name": "Beans", "brand": "HomeSelect"},
    )
    assert items[0]["catalog_status"] == "stockout_pending"
    assert items[0]["resolved"] is False
    assert items[0]["item_id"] is None


def test_apply_substitute_phrase_select_freshfarm() -> None:
    items = _apply_substitute_phrase(
        [
            {
                "item_name": "Beans",
                "brand": "HomeSelect",
                "qty": 1,
                "resolved": False,
                "catalog_status": "stockout_pending",
            }
        ],
        "okk, I select FreshFarm Beans 10",
    )
    assert items[0]["brand"] == "FreshFarm"
    assert items[0]["qty"] == 10
    assert items[0]["catalog_status"] is None


def test_apply_substitute_phrase_multiple_products() -> None:
    items = _apply_substitute_phrase(
        [
            {
                "item_name": "Beans",
                "brand": "HomeSelect",
                "qty": 2,
                "resolved": False,
                "catalog_status": "stockout_pending",
            },
            {
                "item_name": "Milk",
                "brand": "Amul",
                "qty": 10,
                "resolved": False,
                "catalog_status": "stockout_pending",
            },
        ],
        "FreshFarm Beans 2, DairyGold Milk 1",
    )
    assert items[0]["brand"] == "FreshFarm"
    assert items[0]["qty"] == 2
    assert items[1]["brand"] == "DairyGold"
    assert items[1]["qty"] == 1


@pytest.mark.asyncio
async def test_check_availability_flags_all_unavailable_items() -> None:
    deps = _deps()
    deps.catalog_service.stock_by_id = {"beans-oos": 0, "milk-oos": 1}  # type: ignore[attr-defined]
    state = {
        "line_items": [
            {
                "item_name": "Beans",
                "brand": "HomeSelect",
                "item_id": "beans-oos",
                "qty": 2,
                "resolved": True,
                "catalog_status": "resolved",
            },
            {
                "item_name": "Milk",
                "brand": "Amul",
                "item_id": "milk-oos",
                "qty": 10,
                "resolved": True,
                "catalog_status": "resolved",
            },
        ]
    }
    updates = await check_availability(state, deps)
    assert len(updates["unavailable_items"]) == 2
    assert updates["unavailable_items"][0]["item_name"] == "Beans"
    assert updates["unavailable_items"][1]["item_name"] == "Milk"


def test_compute_missing_fields_includes_substitute_when_mixed_cart() -> None:
    missing = _compute_missing_fields(
        {
            "line_items": [
                {
                    "item_name": "Beans",
                    "brand": "HomeSelect",
                    "item_id": "x",
                    "qty": 1,
                    "resolved": False,
                    "catalog_status": "stockout_pending",
                },
                {
                    "item_name": "Milk",
                    "brand": "Amul",
                    "item_id": "y",
                    "qty": 1,
                    "resolved": True,
                    "catalog_status": "resolved",
                },
            ],
            "mandate_verified": True,
            "customer_name": "A",
            "phone": "1",
            "address": "B",
        }
    )
    assert "In-stock alternative for out-of-stock item(s)" in missing


@pytest.mark.asyncio
async def test_oos_alternative_warning_and_audit() -> None:
    memory = FakeMemoryStore()
    alternatives = [
        {
            "item_id": "1",
            "name": "Milk",
            "brand": "BrandB",
            "price_paise": 6000,
            "available_qty": 3,
            "weight_per_unit": "L",
            "expiry_date": "2026-12-31",
        },
        {
            "item_id": "2",
            "name": "Milk",
            "brand": "BrandC",
            "price_paise": 6200,
            "available_qty": 2,
            "weight_per_unit": "L",
            "expiry_date": "2026-12-31",
        },
    ]
    deps = _deps(memory_store=memory, alternatives=alternatives)
    state = {
        "session_id": "s3",
        "line_items": [
            {
                "item_name": "Milk",
                "brand": "BrandA",
                "item_id": "a1",
                "qty": 4,
                "resolved": True,
            }
        ],
        "unavailable_item": {
            "item_id": "a1",
            "item_name": "Milk",
            "brand": "BrandA",
            "requested_qty": 4,
        },
    }
    updates = await suggest_alternative(state, deps)
    assert OUT_OF_STOCK_WARNING_TEMPLATE.splitlines()[0].format(brand="BrandA", item="Milk") in updates["reply"]
    assert "paise" not in updates["reply"].lower()
    assert len(updates["catalog_suggestions"]) <= 3
    assert updates["unavailable_item"] is None
    assert updates["line_items"][0]["catalog_status"] == "stockout_pending"
    assert "Multiple items need substitutes" not in updates["reply"]
    assert memory.audit_events[-1]["action"] == "ITEM_UNAVAILABLE"


@pytest.mark.asyncio
async def test_suggest_alternative_handles_multiple_stockouts() -> None:
    memory = FakeMemoryStore()
    alternatives = [
        {
            "item_id": "1",
            "name": "Milk",
            "brand": "BrandB",
            "price_paise": 6000,
            "available_qty": 3,
            "weight_per_unit": "L",
            "expiry_date": "2026-12-31",
        },
    ]
    deps = _deps(memory_store=memory, alternatives=alternatives)
    state = {
        "session_id": "s-multi",
        "line_items": [
            {
                "item_name": "Beans",
                "brand": "HomeSelect",
                "item_id": "beans-1",
                "qty": 2,
                "resolved": True,
            },
            {
                "item_name": "Milk",
                "brand": "Amul",
                "item_id": "milk-1",
                "qty": 10,
                "resolved": True,
            },
        ],
        "unavailable_items": [
            {
                "item_id": "beans-1",
                "item_name": "Beans",
                "brand": "HomeSelect",
                "requested_qty": 2,
                "available_qty": 0,
            },
            {
                "item_id": "milk-1",
                "item_name": "Milk",
                "brand": "Amul",
                "requested_qty": 10,
                "available_qty": 1,
            },
        ],
    }
    updates = await suggest_alternative(state, deps)
    assert "Multiple items need substitutes" in updates["reply"]
    assert updates["line_items"][0]["catalog_status"] == "stockout_pending"
    assert updates["line_items"][1]["catalog_status"] == "stockout_pending"


@pytest.mark.asyncio
async def test_generate_invoice_total_paise() -> None:
    memory = FakeMemoryStore()
    deps = _deps(memory_store=memory)
    state = {
        "session_id": "s4",
        "consumer_agent_id": "agent-1",
        "mandate_verified": True,
        "customer_name": "Alex",
        "address": "Street 1",
        "phone": "9999999999",
        "line_items": [
            {"item_id": "i1", "item_name": "Beans", "brand": "B1", "qty": 2, "unit_price_paise": 1200},
            {"item_id": "i2", "item_name": "Milk", "brand": "M1", "qty": 1, "unit_price_paise": 3000},
        ],
    }
    updates = await generate_invoice(state, deps)
    assert updates["status"] == "VALIDATED"
    invoice = updates["invoice"]
    assert invoice["subtotal_paise"] == 5400
    assert invoice["discount_paise"] == 0
    assert invoice["taxable_paise"] == 5400
    assert invoice["cgst_paise"] == 135
    assert invoice["sgst_paise"] == 135
    assert invoice["shipping_paise"] == 4000
    assert invoice["total_paise"] == 9670
    assert invoice["customer_name"] == "Alex"
    assert invoice["merchant_name"]
    assert invoice["issued_at"]
