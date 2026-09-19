from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from services.merchant_agent.graph.nodes import (
    NodeDependencies,
    dispatch_invoice_processing,
    resolve_invoice_outcome,
)


class _FakeSession:
    async def commit(self) -> None:
        return None


class _FakeSessionFactory:
    async def __aenter__(self) -> _FakeSession:
        return _FakeSession()

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


class _FakeMemoryStore:
    def __init__(self) -> None:
        self.audit_events: list[dict[str, Any]] = []

    async def append_audit(self, _db_session, *, session_id: str, actor: str, action: str, detail: dict[str, Any]) -> None:
        self.audit_events.append(
            {"session_id": session_id, "actor": actor, "action": action, "detail": detail}
        )


@dataclass
class _FakeReservationClient:
    result: dict[str, Any] | None = None
    err: Exception | None = None
    calls: list[dict[str, Any]] | None = None

    async def submit_invoice(self, invoice: dict[str, Any]) -> dict[str, Any]:
        if self.calls is None:
            self.calls = []
        self.calls.append(invoice)
        if self.err is not None:
            raise self.err
        return dict(self.result or {})


@dataclass
class _FakePaymentClient:
    result: dict[str, Any] | None = None
    err: Exception | None = None
    cancel_err: Exception | None = None
    create_calls: list[dict[str, Any]] | None = None
    cancel_calls: list[dict[str, Any]] | None = None

    async def create_payment_link(self, **payload: Any) -> dict[str, Any]:
        if self.create_calls is None:
            self.create_calls = []
        self.create_calls.append(payload)
        if self.err is not None:
            raise self.err
        return dict(self.result or {})

    async def cancel_payment_link(self, *, merchant_id: str, invoice_id: str) -> dict[str, Any]:
        if self.cancel_calls is None:
            self.cancel_calls = []
        self.cancel_calls.append({"merchant_id": merchant_id, "invoice_id": invoice_id})
        if self.cancel_err is not None:
            raise self.cancel_err
        return {"success": True, "cancelled": True, "invoice_id": invoice_id}


def _deps(
    *,
    memory_store: _FakeMemoryStore,
    reservation_client: _FakeReservationClient | None = None,
    payment_client: _FakePaymentClient | None = None,
) -> NodeDependencies:
    return NodeDependencies(
        llm=None,
        session_factory=lambda: _FakeSessionFactory(),
        catalog_service=None,  # type: ignore[arg-type]
        memory_store=memory_store,  # type: ignore[arg-type]
        invoice_service=None,  # type: ignore[arg-type]
        personal_memory_store=None,  # type: ignore[arg-type]
        reservation_client=reservation_client,
        payment_client=payment_client,
        offer_lookup_tool=None,
        cross_sell_lookup_tool=None,
        campaign_orchestrator_scan_tool=None,
    )


def _base_state() -> dict[str, Any]:
    return {
        "session_id": "sess-dispatch",
        "consumer_agent_id": "consumer-1",
        "merchant_id": "merchant-1",
        "customer_name": "Priya",
        "phone": "+91 9988776655",
        "invoice": {
            "order_id": "inv-1",
            "session_id": "sess-dispatch",
            "issued_at": "2026-09-03T00:00:00+00:00",
            "merchant_name": "Acme Mart",
            "line_items": [{"item_id": "i1", "name": "Milk", "brand": "Amul", "qty": 1, "unit_price_paise": 1000, "line_total_paise": 1000}],
            "subtotal_paise": 1000,
            "discount_paise": 0,
            "taxable_paise": 1000,
            "cgst_paise": 25,
            "sgst_paise": 25,
            "tax_paise": 50,
            "shipping_paise": 0,
            "total_paise": 1050,
            "accepted_offers": [],
        },
    }


@pytest.mark.asyncio
async def test_dispatch_invoice_processing_normalizes_exceptions() -> None:
    memory = _FakeMemoryStore()
    deps = _deps(
        memory_store=memory,
        reservation_client=_FakeReservationClient(result={"success": True, "expires_at": "2026-09-03T01:00:00+00:00"}),
        payment_client=_FakePaymentClient(err=RuntimeError("gateway timeout")),
    )
    updates = await dispatch_invoice_processing(_base_state(), deps)
    assert updates["reservation_result"]["success"] is True
    assert updates["payment_result"]["success"] is False
    assert "gateway timeout" in updates["payment_result"]["error"]["message"]
    assert updates["payment_result"]["error"]["code"] == "UPSTREAM_EXCEPTION"
    assert deps.payment_client.create_calls == [
        {
            "merchant_id": "merchant-1",
            "session_id": "sess-dispatch",
            "invoice_id": "inv-1",
            "amount_paise": 1050,
            "customer_name": "Priya",
            "phone": "+91 9988776655",
            "description": "Invoice inv-1 payment",
        }
    ]


@pytest.mark.asyncio
async def test_resolve_invoice_outcome_both_ok() -> None:
    memory = _FakeMemoryStore()
    deps = _deps(memory_store=memory, payment_client=_FakePaymentClient())
    state = _base_state() | {
        "reservation_result": {"success": True, "expires_at": "2026-09-03T01:10:00+00:00"},
        "payment_result": {
            "success": True,
            "payment_link_url": "https://rzp.io/i/inv-1",
            "expires_at": "2026-09-03T01:05:00+00:00",
        },
    }

    updates = await resolve_invoice_outcome(state, deps)
    assert updates["status"] == "INVOICED"
    assert updates["invoice"]["payment_link_url"] == "https://rzp.io/i/inv-1"
    assert updates["invoice"]["payment_expires_at"] == "2026-09-03T01:05:00+00:00"
    assert updates["invoice"]["reservation_expires_at"] == "2026-09-03T01:10:00+00:00"
    assert memory.audit_events[-1]["action"] == "INVOICE_FULFILLED"


@pytest.mark.asyncio
async def test_resolve_invoice_outcome_reservation_ok_payment_failed() -> None:
    memory = _FakeMemoryStore()
    deps = _deps(memory_store=memory, payment_client=_FakePaymentClient())
    state = _base_state() | {
        "reservation_result": {"success": True, "expires_at": "2026-09-03T01:10:00+00:00"},
        "payment_result": {"success": False, "error": "provider unavailable"},
    }

    updates = await resolve_invoice_outcome(state, deps)
    assert updates["status"] == "INVOICED"
    assert "payment link generation failed" in updates["reply"].lower()
    assert updates["reservation_expires_at"] == "2026-09-03T01:10:00+00:00"
    assert memory.audit_events[-1]["action"] == "PAYMENT_LINK_FAILED"


@pytest.mark.asyncio
async def test_resolve_invoice_outcome_reservation_failed_payment_ok() -> None:
    memory = _FakeMemoryStore()
    payment_client = _FakePaymentClient()
    deps = _deps(memory_store=memory, payment_client=payment_client)
    state = _base_state() | {
        "reservation_result": {"success": False, "unavailable_items": [{"item_id": "i1", "item_name": "Milk"}]},
        "payment_result": {"success": True, "payment_link_url": "https://rzp.io/i/inv-1"},
    }

    updates = await resolve_invoice_outcome(state, deps)
    assert updates["status"] == "AWAITING_FIELDS"
    assert updates["invoice"] is None
    assert updates["unavailable_items"][0]["item_id"] == "i1"
    assert payment_client.cancel_calls == [{"merchant_id": "merchant-1", "invoice_id": "inv-1"}]
    assert memory.audit_events[-1]["action"] == "RESERVATION_FAILED_PAYMENT_VOIDED"


@pytest.mark.asyncio
async def test_resolve_invoice_outcome_both_failed() -> None:
    memory = _FakeMemoryStore()
    deps = _deps(memory_store=memory, payment_client=_FakePaymentClient())
    state = _base_state() | {
        "reservation_result": {"success": False, "unavailable_items": [{"item_id": "i1"}]},
        "payment_result": {"success": False, "error": "provider unavailable"},
    }

    updates = await resolve_invoice_outcome(state, deps)
    assert updates["status"] == "AWAITING_FIELDS"
    assert updates["invoice"] is None
    assert updates["unavailable_item"]["item_id"] == "i1"
    assert memory.audit_events[-1]["action"] == "RESERVATION_FAILED"


@pytest.mark.asyncio
async def test_resolve_invoice_outcome_logs_orphaned_payment_link_risk_when_cancel_fails() -> None:
    memory = _FakeMemoryStore()
    payment_client = _FakePaymentClient(cancel_err=RuntimeError("cancel gateway timeout"))
    deps = _deps(memory_store=memory, payment_client=payment_client)
    state = _base_state() | {
        "reservation_result": {"success": False, "unavailable_items": [{"item_id": "i1", "item_name": "Milk"}]},
        "payment_result": {"success": True, "payment_link_url": "https://rzp.io/i/inv-1"},
    }

    updates = await resolve_invoice_outcome(state, deps)
    assert updates["status"] == "AWAITING_FIELDS"
    assert payment_client.cancel_calls == [{"merchant_id": "merchant-1", "invoice_id": "inv-1"}]
    assert any(event["action"] == "ORPHANED_PAYMENT_LINK_RISK" for event in memory.audit_events)
