from __future__ import annotations

from uuid import uuid4

import pytest

from services.reservation_service.reservation_service import ReservationService
from shared.schemas.invoice import Invoice, InvoiceLineItem


class FakeSession:
    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def begin(self) -> "FakeSession":
        return self


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def __call__(self) -> FakeSession:
        return self._session


class FakeInvoiceStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def store_invoice(self, invoice_id: str, invoice_payload: dict[str, object]) -> None:
        self.calls.append((invoice_id, invoice_payload))


def _build_invoice(order_id: str, item_id: str, qty: int) -> Invoice:
    return Invoice(
        order_id=order_id,
        session_id="session-1",
        issued_at="2026-09-03T00:00:00+00:00",
        merchant_name="Acme Mart",
        customer_name="Tester",
        address="City",
        phone_number="9999999999",
        line_items=[
            InvoiceLineItem(
                item_id=item_id,
                name="Milk",
                brand="Brand A",
                qty=qty,
                unit_price_paise=1000,
                line_total_paise=1000 * qty,
                weight_per_unit="1L",
            )
        ],
        subtotal_paise=1000 * qty,
        discount_paise=0,
        taxable_paise=1000 * qty,
        cgst_paise=0,
        sgst_paise=0,
        tax_paise=0,
        shipping_paise=0,
        total_paise=1000 * qty,
        accepted_offers=[],
    )


@pytest.mark.asyncio
async def test_reserve_success_path() -> None:
    session = FakeSession()
    invoice_store = FakeInvoiceStore()
    service = ReservationService(
        session_factory=FakeSessionFactory(session),
        redis_client=None,
        invoice_store=invoice_store,
    )
    order_id = str(uuid4())
    item_id = str(uuid4())
    invoice = _build_invoice(order_id, item_id, 2)
    seen = {"insert_called": False, "refresh_called": False}

    async def always_reserve(*_args, **_kwargs) -> bool:
        return True

    async def mark_insert(*_args, **_kwargs) -> None:
        seen["insert_called"] = True

    async def mark_refresh(*_args, **_kwargs) -> None:
        seen["refresh_called"] = True

    service._decrement_stock_if_available = always_reserve  # type: ignore[method-assign]
    service._insert_held_rows = mark_insert  # type: ignore[method-assign]
    service._refresh_catalog_cache = mark_refresh  # type: ignore[method-assign]

    result = await service.reserve(invoice)

    assert result["success"] is True
    assert result["unavailable_items"] == []
    assert "invoice" not in result or result["invoice"] is None
    assert result["reserved_at"] is not None
    assert result["expires_at"] is not None
    assert seen["insert_called"] is True
    assert seen["refresh_called"] is True
    assert invoice_store.calls and invoice_store.calls[0][0] == order_id


@pytest.mark.asyncio
async def test_reserve_insufficient_stock_rolls_back() -> None:
    session = FakeSession()
    invoice_store = FakeInvoiceStore()
    service = ReservationService(
        session_factory=FakeSessionFactory(session),
        redis_client=None,
        invoice_store=invoice_store,
    )
    order_id = str(uuid4())
    first_item_id = str(uuid4())
    second_item_id = str(uuid4())
    invoice = _build_invoice(order_id, first_item_id, 1)
    invoice.line_items.append(
        InvoiceLineItem(
            item_id=second_item_id,
            name="Bread",
            brand="Brand B",
            qty=1,
            unit_price_paise=2000,
            line_total_paise=2000,
            weight_per_unit="500g",
        )
    )
    seen = {"insert_called": False, "refresh_called": False}

    async def conditional_reserve(_db_session, *, item_id, qty) -> bool:
        _ = qty
        return str(item_id) != second_item_id

    async def mark_insert(*_args, **_kwargs) -> None:
        seen["insert_called"] = True

    async def mark_refresh(*_args, **_kwargs) -> None:
        seen["refresh_called"] = True

    async def available_qty(*_args, **_kwargs) -> int:
        return 0

    service._decrement_stock_if_available = conditional_reserve  # type: ignore[method-assign]
    service._insert_held_rows = mark_insert  # type: ignore[method-assign]
    service._refresh_catalog_cache = mark_refresh  # type: ignore[method-assign]
    service._fetch_available_qty = available_qty  # type: ignore[method-assign]

    result = await service.reserve(invoice)

    assert result["success"] is False
    assert result["unavailable_items"] == [
        {"item_id": second_item_id, "requested_qty": 1, "available_qty": 0}
    ]
    assert "invoice" not in result or result["invoice"] is None
    assert result["reserved_at"] is None
    assert result["expires_at"] is None
    assert seen["insert_called"] is False
    assert seen["refresh_called"] is False
    assert invoice_store.calls == []


@pytest.mark.asyncio
async def test_reserve_accepts_invoice_id_and_line_items_shape() -> None:
    session = FakeSession()
    invoice_store = FakeInvoiceStore()
    service = ReservationService(
        session_factory=FakeSessionFactory(session),
        redis_client=None,
        invoice_store=invoice_store,
    )
    order_id = str(uuid4())
    item_id = str(uuid4())

    async def always_reserve(*_args, **_kwargs) -> bool:
        return True

    async def noop_insert(*_args, **_kwargs) -> None:
        return None

    async def noop_refresh(*_args, **_kwargs) -> None:
        return None

    service._decrement_stock_if_available = always_reserve  # type: ignore[method-assign]
    service._insert_held_rows = noop_insert  # type: ignore[method-assign]
    service._refresh_catalog_cache = noop_refresh  # type: ignore[method-assign]

    result = await service.reserve(
        invoice_id=order_id,
        line_items=[{"item_id": item_id, "qty": 2}],
    )

    assert result["success"] is True
    assert result["unavailable_items"] == []
    assert result["reserved_at"] is not None
    assert result["expires_at"] is not None
    assert invoice_store.calls and invoice_store.calls[0][0] == order_id
