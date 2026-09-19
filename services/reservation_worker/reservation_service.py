from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.config import get_settings
from shared.models.audit_log import AuditLog
from shared.models.item import Item
from shared.models.reserved_item import ReservedItem
from shared.redis_client import get_redis_client

HELD = "HELD"
COMMITTED = "COMMITTED"
RELEASED = "RELEASED"


class ReservationError(Exception):
    pass


class ReservationInsufficientStockError(ReservationError):
    pass


@dataclass(slots=True)
class ReservationLineItem:
    item_id: UUID
    qty: int


class ReservationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client or get_redis_client()
        self._settings = get_settings()

    def _reserved_key(self, item_id: UUID) -> str:
        return f"reserved:item:{item_id}"

    @staticmethod
    def _normalize_invoice_id(invoice_id: str | UUID) -> UUID:
        return invoice_id if isinstance(invoice_id, UUID) else UUID(str(invoice_id))

    @staticmethod
    def _normalize_line_items(line_items: list[dict]) -> list[ReservationLineItem]:
        normalized: list[ReservationLineItem] = []
        for line in line_items:
            raw_item_id = line.get("item_id")
            raw_qty = line.get("qty", line.get("reserved_qty"))
            if raw_item_id is None or raw_qty is None:
                raise ReservationError("line_items must include item_id and qty")
            qty = int(raw_qty)
            if qty <= 0:
                raise ReservationError("qty must be > 0")
            normalized.append(ReservationLineItem(item_id=UUID(str(raw_item_id)), qty=qty))
        if not normalized:
            raise ReservationError("line_items cannot be empty")
        return normalized

    async def _load_item_for_update(self, db_session: AsyncSession, item_id: UUID) -> Item | None:
        stmt: Select[tuple[Item]] = (
            select(Item).where(Item.id == item_id, Item.is_active.is_(True)).with_for_update()
        )
        return (await db_session.execute(stmt)).scalar_one_or_none()

    async def _fetch_held_rows_for_invoice(
        self, db_session: AsyncSession, invoice_id: UUID
    ) -> list[ReservedItem]:
        return (
            await db_session.execute(
                select(ReservedItem)
                .where(ReservedItem.invoice_id == invoice_id, ReservedItem.status == HELD)
                .with_for_update()
            )
        ).scalars().all()

    async def _fetch_expired_held_rows(self, db_session: AsyncSession, now: datetime) -> list[ReservedItem]:
        return (
            await db_session.execute(
                select(ReservedItem)
                .where(ReservedItem.status == HELD, ReservedItem.expires_at <= now)
                .with_for_update()
            )
        ).scalars().all()

    async def _get_reserved_qty(self, item_id: UUID) -> int:
        raw = await self._redis.get(self._reserved_key(item_id))
        return int(raw or 0)

    async def _decrement_reserved_counter(self, item_id: UUID, qty: int) -> None:
        key = self._reserved_key(item_id)
        remaining = await self._redis.decrby(key, qty)
        if int(remaining) <= 0:
            await self._redis.delete(key)

    async def true_available(self, item_id: str | UUID) -> dict[str, int | str]:
        normalized_item_id = item_id if isinstance(item_id, UUID) else UUID(str(item_id))
        async with self._session_factory() as db_session:
            item = (await db_session.execute(select(Item).where(Item.id == normalized_item_id))).scalar_one_or_none()
            if item is None:
                raise ReservationError(f"Item {normalized_item_id} not found")
            reserved_qty = await self._get_reserved_qty(normalized_item_id)
            quantity_available = int(item.quantity_available)
            return {
                "item_id": str(normalized_item_id),
                "true_available_qty": quantity_available - reserved_qty,
                "quantity_available": quantity_available,
                "reserved_qty": reserved_qty,
            }

    async def reserve(self, invoice_id: str | UUID, line_items: list[dict]) -> dict[str, object]:
        normalized_invoice_id = self._normalize_invoice_id(invoice_id)
        normalized_lines = self._normalize_line_items(line_items)
        incremented: list[ReservationLineItem] = []
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=int(self._settings.reservation_hold_ttl_seconds))
        held_rows: list[ReservedItem] = []

        try:
            async with self._session_factory() as db_session:
                async with db_session.begin():
                    for line in normalized_lines:
                        item = await self._load_item_for_update(db_session, line.item_id)
                        if item is None:
                            raise ReservationError(f"Item {line.item_id} not found")

                        reserved_qty = await self._get_reserved_qty(line.item_id)
                        true_available = int(item.quantity_available) - reserved_qty
                        if true_available < line.qty:
                            raise ReservationInsufficientStockError(
                                f"Insufficient stock for item {line.item_id}. "
                                f"Requested {line.qty}, true_available {true_available}."
                            )

                    for line in normalized_lines:
                        held = ReservedItem(
                            invoice_id=normalized_invoice_id,
                            item_id=line.item_id,
                            reserved_qty=line.qty,
                            reserved_at=now,
                            expires_at=expires_at,
                            status=HELD,
                        )
                        db_session.add(held)
                        held_rows.append(held)

                    await db_session.flush()
                    for line in normalized_lines:
                        await self._redis.incrby(self._reserved_key(line.item_id), line.qty)
                        incremented.append(line)
        except Exception:
            for line in incremented:
                await self._decrement_reserved_counter(line.item_id, line.qty)
            raise

        return {
            "invoice_id": str(normalized_invoice_id),
            "status": HELD,
            "expires_at": expires_at.isoformat(),
            "lines": [
                {"item_id": str(row.item_id), "reserved_qty": int(row.reserved_qty), "reservation_id": str(row.id)}
                for row in held_rows
            ],
        }

    async def commit(self, invoice_id: str | UUID) -> dict[str, object]:
        normalized_invoice_id = self._normalize_invoice_id(invoice_id)
        item_qty_map: dict[UUID, int] = defaultdict(int)
        committed_count = 0

        async with self._session_factory() as db_session:
            async with db_session.begin():
                held_rows = await self._fetch_held_rows_for_invoice(db_session, normalized_invoice_id)
                if not held_rows:
                    return {"invoice_id": str(normalized_invoice_id), "status": COMMITTED, "committed_rows": 0}

                for row in held_rows:
                    item_qty_map[row.item_id] += int(row.reserved_qty)
                    row.status = COMMITTED
                    committed_count += 1

                for item_id, total_qty in item_qty_map.items():
                    item = await self._load_item_for_update(db_session, item_id)
                    if item is None:
                        raise ReservationError(f"Item {item_id} not found")
                    if int(item.quantity_available) < total_qty:
                        raise ReservationInsufficientStockError(
                            f"Insufficient stock while committing item {item_id}. "
                            f"Available {item.quantity_available}, required {total_qty}."
                        )
                    item.quantity_available = int(item.quantity_available) - total_qty

                await db_session.flush()

        for item_id, total_qty in item_qty_map.items():
            await self._decrement_reserved_counter(item_id, total_qty)

        return {
            "invoice_id": str(normalized_invoice_id),
            "status": COMMITTED,
            "committed_rows": committed_count,
        }

    async def release(self, invoice_id: str | UUID) -> dict[str, object]:
        normalized_invoice_id = self._normalize_invoice_id(invoice_id)
        item_qty_map: dict[UUID, int] = defaultdict(int)
        released_count = 0

        async with self._session_factory() as db_session:
            async with db_session.begin():
                held_rows = await self._fetch_held_rows_for_invoice(db_session, normalized_invoice_id)
                if not held_rows:
                    return {"invoice_id": str(normalized_invoice_id), "status": RELEASED, "released_rows": 0}

                for row in held_rows:
                    row.status = RELEASED
                    item_qty_map[row.item_id] += int(row.reserved_qty)
                    released_count += 1

                await db_session.flush()

        for item_id, total_qty in item_qty_map.items():
            await self._decrement_reserved_counter(item_id, total_qty)

        return {
            "invoice_id": str(normalized_invoice_id),
            "status": RELEASED,
            "released_rows": released_count,
        }

    async def release_expired_holds(self) -> list[dict[str, object]]:
        now = datetime.now(timezone.utc)
        item_qty_map: dict[UUID, int] = defaultdict(int)
        released_per_invoice: dict[UUID, int] = defaultdict(int)

        async with self._session_factory() as db_session:
            async with db_session.begin():
                expired_rows = await self._fetch_expired_held_rows(db_session, now)

                for row in expired_rows:
                    row.status = RELEASED
                    item_qty_map[row.item_id] += int(row.reserved_qty)
                    released_per_invoice[row.invoice_id] += 1

                for invoice_id, rows_count in released_per_invoice.items():
                    db_session.add(
                        AuditLog(
                            session_id=str(invoice_id),
                            actor="reservation_worker",
                            action="RESERVATION_EXPIRED_ROLLED_BACK",
                            detail={"invoice_id": str(invoice_id), "released_rows": rows_count},
                        )
                    )

                await db_session.flush()

        for item_id, total_qty in item_qty_map.items():
            await self._decrement_reserved_counter(item_id, total_qty)

        return [
            {"invoice_id": str(invoice_id), "released_rows": rows_count}
            for invoice_id, rows_count in released_per_invoice.items()
        ]
