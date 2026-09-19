from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.merchant_agent.catalog_service import refresh_catalog_items
from services.reservation_service.invoice_store import InvoiceStore
from shared.config import get_settings
from shared.models.audit_log import AuditLog
from shared.models.item import Item
from shared.models.reserved_item import ReservedItem
from shared.redis_client import get_redis_client
from shared.schemas.invoice import Invoice

HELD = "HELD"
RELEASED = "RELEASED"
PAID = "PAID"


@dataclass(slots=True)
class ReservationLineItem:
    item_id: UUID
    qty: int


class _InsufficientStockError(Exception):
    def __init__(self, unavailable_items: list[dict[str, object]]) -> None:
        super().__init__("insufficient stock")
        self.unavailable_items = unavailable_items


class ReservationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        redis_client: Redis | None = None,
        invoice_store: InvoiceStore | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client or get_redis_client()
        self._settings = get_settings()
        self._invoice_store = invoice_store or InvoiceStore(redis_client=self._redis)

    @staticmethod
    def _normalize_line_items(invoice: Invoice) -> list[ReservationLineItem]:
        normalized: list[ReservationLineItem] = []
        for line in invoice.line_items:
            qty = int(line.qty)
            if qty <= 0:
                raise ValueError("line item qty must be greater than zero")
            normalized.append(ReservationLineItem(item_id=UUID(str(line.item_id)), qty=qty))
        if not normalized:
            raise ValueError("invoice line_items cannot be empty")
        return normalized

    @staticmethod
    def _normalize_payload_line_items(line_items: list[dict[str, object]]) -> list[ReservationLineItem]:
        normalized: list[ReservationLineItem] = []
        for line in line_items:
            qty = int(line.get("qty", 0))
            if qty <= 0:
                raise ValueError("line item qty must be greater than zero")
            normalized.append(
                ReservationLineItem(
                    item_id=UUID(str(line["item_id"])),
                    qty=qty,
                )
            )
        if not normalized:
            raise ValueError("line_items cannot be empty")
        return normalized

    async def _decrement_stock_if_available(
        self, db_session: AsyncSession, *, item_id: UUID, qty: int
    ) -> bool:
        result = await db_session.execute(
            update(Item)
            .where(Item.id == item_id, Item.quantity_available >= qty, Item.is_active.is_(True))
            .values(quantity_available=Item.quantity_available - qty)
        )
        return bool(result.rowcount)

    async def _fetch_available_qty(self, db_session: AsyncSession, *, item_id: UUID) -> int:
        available_qty = (
            await db_session.execute(
                select(Item.quantity_available).where(
                    Item.id == item_id,
                    Item.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        return int(available_qty or 0)

    async def _insert_held_rows(
        self,
        db_session: AsyncSession,
        *,
        invoice_id: UUID,
        lines: list[ReservationLineItem],
        reserved_at: datetime,
        expires_at: datetime,
    ) -> None:
        db_session.add_all(
            [
                ReservedItem(
                    invoice_id=invoice_id,
                    item_id=line.item_id,
                    reserved_qty=line.qty,
                    reserved_at=reserved_at,
                    expires_at=expires_at,
                    status=HELD,
                )
                for line in lines
            ]
        )
        await db_session.flush()

    async def _refresh_catalog_cache(self, item_ids: list[UUID]) -> None:
        if not item_ids:
            return
        unique_item_ids = sorted({item_id for item_id in item_ids}, key=str)
        async with self._session_factory() as db_session:
            items = (
                await db_session.execute(select(Item).where(Item.id.in_(unique_item_ids)))
            ).scalars().all()
        if items:
            await refresh_catalog_items(self._redis, list(items), self._settings.catalog_cache_ttl_seconds)

    async def reserve(
        self,
        invoice: Invoice | None = None,
        *,
        invoice_id: str | UUID | None = None,
        line_items: list[dict[str, object]] | None = None,
        invoice_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if invoice is not None:
            normalized_invoice_id = UUID(str(invoice.order_id))
            lines = self._normalize_line_items(invoice)
            payload_to_store = invoice.model_dump(mode="json")
        else:
            if invoice_id is None:
                raise ValueError("invoice_id is required when invoice is not provided")
            if not line_items:
                raise ValueError("line_items are required when invoice is not provided")
            normalized_invoice_id = UUID(str(invoice_id))
            lines = self._normalize_payload_line_items(line_items)
            payload_to_store = invoice_payload or {
                "order_id": str(normalized_invoice_id),
                "line_items": [{"item_id": str(line.item_id), "qty": int(line.qty)} for line in lines],
            }

        reserved_at = datetime.now(timezone.utc)
        expires_at = reserved_at + timedelta(seconds=int(self._settings.reservation_ttl_seconds))
        unavailable_items: list[dict[str, object]] = []

        async with self._session_factory() as db_session:
            try:
                async with db_session.begin():
                    for line in lines:
                        reserved = await self._decrement_stock_if_available(
                            db_session,
                            item_id=line.item_id,
                            qty=line.qty,
                        )
                        if not reserved:
                            available_qty = await self._fetch_available_qty(
                                db_session,
                                item_id=line.item_id,
                            )
                            unavailable_items.append(
                                {
                                    "item_id": str(line.item_id),
                                    "requested_qty": int(line.qty),
                                    "available_qty": int(available_qty),
                                }
                            )
                    if unavailable_items:
                        raise _InsufficientStockError(unavailable_items)
                    await self._insert_held_rows(
                        db_session,
                        invoice_id=normalized_invoice_id,
                        lines=lines,
                        reserved_at=reserved_at,
                        expires_at=expires_at,
                    )
            except _InsufficientStockError as exc:
                return {
                    "success": False,
                    "unavailable_items": exc.unavailable_items,
                    "reserved_at": None,
                    "expires_at": None,
                }

        await self._refresh_catalog_cache([line.item_id for line in lines])
        await self._invoice_store.store_invoice(str(normalized_invoice_id), payload_to_store)
        return {
            "success": True,
            "unavailable_items": [],
            "reserved_at": reserved_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

    async def rollback_expired_holds(self) -> list[str]:
        now = datetime.now(timezone.utc)
        restored_item_ids: list[UUID] = []
        released_by_invoice: dict[str, int] = defaultdict(int)

        async with self._session_factory() as db_session:
            async with db_session.begin():
                expired_rows = (
                    await db_session.execute(
                        select(ReservedItem)
                        .where(ReservedItem.status == HELD, ReservedItem.expires_at <= now)
                        .with_for_update()
                    )
                ).scalars().all()

                for row in expired_rows:
                    released = await db_session.execute(
                        update(ReservedItem)
                        .where(ReservedItem.id == row.id, ReservedItem.status == HELD)
                        .values(status=RELEASED)
                    )
                    if not released.rowcount:
                        continue
                    row.status = RELEASED
                    restored_item_ids.append(row.item_id)
                    released_by_invoice[str(row.invoice_id)] += 1
                    await db_session.execute(
                        update(Item)
                        .where(Item.id == row.item_id)
                        .values(quantity_available=Item.quantity_available + int(row.reserved_qty))
                    )
                for invoice_id, released_rows in released_by_invoice.items():
                    db_session.add(
                        AuditLog(
                            session_id=invoice_id,
                            actor="reservation_service",
                            action="RESERVATION_EXPIRED_ROLLED_BACK",
                            detail={"invoice_id": invoice_id, "released_rows": released_rows},
                        )
                    )

        if restored_item_ids:
            await self._refresh_catalog_cache(restored_item_ids)
        return sorted(released_by_invoice.keys())

    async def mark_reserved_paid(self, invoice_id: str | UUID) -> int:
        normalized_invoice_id = UUID(str(invoice_id))
        async with self._session_factory() as db_session:
            async with db_session.begin():
                result = await db_session.execute(
                    update(ReservedItem)
                    .where(
                        ReservedItem.invoice_id == normalized_invoice_id,
                        ReservedItem.status == HELD,
                    )
                    .values(status=PAID)
                )
        return int(result.rowcount or 0)
