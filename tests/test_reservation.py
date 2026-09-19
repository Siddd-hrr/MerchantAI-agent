from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from services.reservation_worker.reservation_service import (
    HELD,
    RELEASED,
    ReservationInsufficientStockError,
    ReservationService,
)
from shared.models.reserved_item import ReservedItem


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        value = self._store.get(key)
        return None if value is None else str(value)

    async def incrby(self, key: str, amount: int) -> int:
        self._store[key] = int(self._store.get(key, 0)) + int(amount)
        return self._store[key]

    async def decrby(self, key: str, amount: int) -> int:
        self._store[key] = int(self._store.get(key, 0)) - int(amount)
        return self._store[key]

    async def delete(self, key: str) -> int:
        existed = 1 if key in self._store else 0
        self._store.pop(key, None)
        return existed


class FakeItem:
    def __init__(self, item_id: UUID, quantity_available: int) -> None:
        self.id = item_id
        self.quantity_available = quantity_available
        self.is_active = True


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def begin(self) -> FakeSession:
        return self

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def __call__(self) -> FakeSession:
        return self._session


@pytest.mark.asyncio
async def test_reserve_success() -> None:
    redis = FakeRedis()
    session = FakeSession()
    service = ReservationService(session_factory=FakeSessionFactory(session), redis_client=redis)
    item_id = uuid4()
    invoice_id = uuid4()

    async def fake_lock_item(_db_session, lookup_item_id: UUID):
        assert lookup_item_id == item_id
        return FakeItem(item_id, quantity_available=1)

    service._load_item_for_update = fake_lock_item  # type: ignore[method-assign]

    result = await service.reserve(str(invoice_id), [{"item_id": str(item_id), "qty": 1}])

    assert result["invoice_id"] == str(invoice_id)
    assert result["status"] == HELD
    assert await redis.get(f"reserved:item:{item_id}") == "1"
    held_rows = [obj for obj in session.added if isinstance(obj, ReservedItem)]
    assert len(held_rows) == 1
    assert held_rows[0].status == HELD


@pytest.mark.asyncio
async def test_second_reserve_for_last_unit_fails() -> None:
    redis = FakeRedis()
    session = FakeSession()
    service = ReservationService(session_factory=FakeSessionFactory(session), redis_client=redis)
    item_id = uuid4()

    async def fake_lock_item(_db_session, _lookup_item_id: UUID):
        return FakeItem(item_id, quantity_available=1)

    service._load_item_for_update = fake_lock_item  # type: ignore[method-assign]

    await service.reserve(str(uuid4()), [{"item_id": str(item_id), "qty": 1}])
    with pytest.raises(ReservationInsufficientStockError):
        await service.reserve(str(uuid4()), [{"item_id": str(item_id), "qty": 1}])

    assert await redis.get(f"reserved:item:{item_id}") == "1"


@pytest.mark.asyncio
async def test_release_path_updates_status_and_redis() -> None:
    redis = FakeRedis()
    session = FakeSession()
    service = ReservationService(session_factory=FakeSessionFactory(session), redis_client=redis)
    item_id = uuid4()
    invoice_id = uuid4()

    held_row = ReservedItem(
        invoice_id=invoice_id,
        item_id=item_id,
        reserved_qty=2,
        reserved_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        status=HELD,
    )
    await redis.incrby(f"reserved:item:{item_id}", 2)

    async def fake_fetch_held_rows(_db_session, lookup_invoice_id: UUID):
        assert lookup_invoice_id == invoice_id
        return [held_row]

    service._fetch_held_rows_for_invoice = fake_fetch_held_rows  # type: ignore[method-assign]

    result = await service.release(str(invoice_id))

    assert result["status"] == RELEASED
    assert result["released_rows"] == 1
    assert held_row.status == RELEASED
    assert await redis.get(f"reserved:item:{item_id}") is None
