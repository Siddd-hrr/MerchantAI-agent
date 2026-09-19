from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from shared.schemas.catalog import CatalogSuggestion
from shared.schemas.invoice import Invoice

OrderStatus = Literal["DRAFT", "AWAITING_FIELDS", "AWAITING_CONFIRMATION", "VALIDATED", "INVOICED", "FAILED"]


class DraftLineItem(BaseModel):
    item_name: str
    brand: str | None = None
    qty: int | None = Field(default=None, ge=1)
    item_id: str | None = None
    weight_per_unit: str | None = None
    expiry_date: str | None = None
    unit_price_paise: int | None = Field(default=None, ge=0)
    available_qty: int | None = Field(default=None, ge=0)
    resolved: bool = False


class OrderStateModel(BaseModel):
    session_id: str
    consumer_agent_id: str
    message: str
    mandate_verified: bool = False
    line_items: list[DraftLineItem] = Field(default_factory=list)
    customer_name: str | None = None
    address: str | None = None
    phone: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    catalog_suggestions: list[CatalogSuggestion] = Field(default_factory=list)
    status: OrderStatus = "DRAFT"
    reply: str = ""
    invoice: Invoice | None = None
    error: dict[str, Any] | None = None
    off_topic: bool = False
    unavailable_item: dict[str, Any] | None = None
    unavailable_items: list[dict[str, Any]] = Field(default_factory=list)
    intent_updates: dict[str, Any] = Field(default_factory=dict)
    resolved_offers: list[dict[str, Any]] = Field(default_factory=list)
    cross_sell_candidates: list[dict[str, Any]] = Field(default_factory=list)
    campaign_context: list[dict[str, Any]] = Field(default_factory=list)
    personal_memory_snapshot: dict[str, Any] = Field(default_factory=dict)
    react_scratchpad: list[dict[str, Any]] = Field(default_factory=list)
    reservation_invoice_id: str | None = None
    merchant_id: str | None = None
    reservation_result: dict[str, Any] | None = None
    payment_result: dict[str, Any] | None = None
    payment_link_url: str | None = None
    payment_expires_at: str | None = None
    reservation_expires_at: str | None = None
    react_loop_count: int = 0
    react_goal: str | None = None
    react_selected_tools: list[str] = Field(default_factory=list)
    react_loop_capped: bool = False
    react_should_continue: bool = False
    awaiting_invoice_confirmation: bool = False
    invoice_proceed: bool = False


class OrderState(TypedDict, total=False):
    session_id: str
    consumer_agent_id: str
    message: str
    mandate_verified: bool
    line_items: list[dict[str, Any]]
    customer_name: str | None
    address: str | None
    phone: str | None
    missing_fields: list[str]
    catalog_suggestions: list[dict[str, Any]]
    status: OrderStatus
    reply: str
    invoice: dict[str, Any] | None
    error: dict[str, Any] | None
    off_topic: bool
    unavailable_item: dict[str, Any] | None
    unavailable_items: list[dict[str, Any]]
    intent_updates: dict[str, Any]
    resolved_offers: list[dict[str, Any]]
    cross_sell_candidates: list[dict[str, Any]]
    campaign_context: list[dict[str, Any]]
    personal_memory_snapshot: dict[str, Any]
    react_scratchpad: list[dict[str, Any]]
    reservation_invoice_id: str | None
    merchant_id: str | None
    reservation_result: dict[str, Any] | None
    payment_result: dict[str, Any] | None
    payment_link_url: str | None
    payment_expires_at: str | None
    reservation_expires_at: str | None
    react_loop_count: int
    react_goal: str | None
    react_selected_tools: list[str]
    react_loop_capped: bool
    react_should_continue: bool
    awaiting_invoice_confirmation: bool
    invoice_proceed: bool
