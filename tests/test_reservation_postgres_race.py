"""Postgres integration: last-unit race must leave exactly one winner.

Requires a reachable DATABASE_URL (default docker-compose host port 5433).
Skip when Postgres is unavailable so unit CI stays green.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.reservation_service.invoice_store import InvoiceStore
from services.reservation_service.reservation_service import ReservationService
from shared.config import get_settings
from shared.models.item import Item
from shared.models.reserved_item import ReservedItem
from shared.schemas.invoice import Invoice, InvoiceLineItem


class _MemoryRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.ttls[key] = ex

    async def delete(self, key: str) -> int:
        existed = 1 if key in self.store else 0
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return existed


def _database_url() -> str:
    return os.getenv("DATABASE_URL") or get_settings().database_url


async def _postgres_reachable(url: str) -> bool:
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


def _invoice_for(*, item_id, name: str, brand: str, weight: str, price: int, order_id: str) -> Invoice:
    return Invoice(
        order_id=order_id,
        session_id=str(uuid4()),
        issued_at="2026-09-09T00:00:00+00:00",
        merchant_name="Acme Mart",
        customer_name="Race Tester",
        address="City",
        phone_number="9999999999",
        line_items=[
            InvoiceLineItem(
                item_id=str(item_id),
                name=name,
                brand=brand,
                qty=1,
                unit_price_paise=price,
                line_total_paise=price,
                weight_per_unit=weight,
            )
        ],
        subtotal_paise=price,
        discount_paise=0,
        taxable_paise=price,
        cgst_paise=0,
        sgst_paise=0,
        tax_paise=0,
        shipping_paise=0,
        total_paise=price,
        accepted_offers=[],
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_last_unit_only_one_succeeds() -> None:
    url = _database_url()
    if not await _postgres_reachable(url):
        pytest.skip(f"Postgres not reachable at {url}")

    engine = create_async_engine(url, pool_pre_ping=True)
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    item_id = uuid4()
    invoice_ids: list[str] = []

    try:
        async with session_factory() as session:
            async with session.begin():
                session.add(
                    Item(
                        id=item_id,
                        name="Race Milk",
                        brand="RaceBrand",
                        weight_per_unit="1L",
                        price_paise=1000,
                        quantity_available=1,
                        expiry_date=date.today() + timedelta(days=30),
                        is_active=True,
                    )
                )

        redis = _MemoryRedis()
        invoice_store = InvoiceStore(redis_client=redis)  # type: ignore[arg-type]

        def make_service() -> ReservationService:
            svc = ReservationService(
                session_factory=session_factory,
                redis_client=redis,  # type: ignore[arg-type]
                invoice_store=invoice_store,
            )

            async def noop_refresh(_item_ids: list) -> None:
                return None

            svc._refresh_catalog_cache = noop_refresh  # type: ignore[method-assign]
            return svc

        inv_a = _invoice_for(
            item_id=item_id,
            name="Race Milk",
            brand="RaceBrand",
            weight="1L",
            price=1000,
            order_id=str(uuid4()),
        )
        inv_b = _invoice_for(
            item_id=item_id,
            name="Race Milk",
            brand="RaceBrand",
            weight="1L",
            price=1000,
            order_id=str(uuid4()),
        )
        invoice_ids = [inv_a.order_id, inv_b.order_id]

        results = await asyncio.gather(
            make_service().reserve(inv_a),
            make_service().reserve(inv_b),
        )
        successes = [r for r in results if r.get("success") is True]
        failures = [r for r in results if r.get("success") is False]

        assert len(successes) == 1, results
        assert len(failures) == 1, results
        assert failures[0]["unavailable_items"][0]["item_id"] == str(item_id)
        assert failures[0]["unavailable_items"][0]["available_qty"] == 0

        async with session_factory() as session:
            qty = (
                await session.execute(select(Item.quantity_available).where(Item.id == item_id))
            ).scalar_one()
            held = (
                await session.execute(
                    select(ReservedItem).where(
                        ReservedItem.item_id == item_id,
                        ReservedItem.status == "HELD",
                    )
                )
            ).scalars().all()

        assert int(qty) == 0
        assert len(held) == 1
    finally:
        async with session_factory() as session:
            async with session.begin():
                for inv in invoice_ids:
                    await session.execute(
                        text("DELETE FROM reserved_items WHERE invoice_id = CAST(:iid AS uuid)"),
                        {"iid": inv},
                    )
                await session.execute(
                    text("DELETE FROM items WHERE id = CAST(:id AS uuid)"),
                    {"id": str(item_id)},
                )
        await engine.dispose()
