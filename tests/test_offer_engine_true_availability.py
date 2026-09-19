from __future__ import annotations

import json
from collections.abc import Iterable
from uuid import uuid4

import pytest
from fastapi import HTTPException

from services.offer_engine.availability_client import AvailabilityClient
from services.offer_engine.routers.catalog import get_pickable_items
from services.offer_engine.routers.combos import ComboCreateRequest, create_combo
from services.offer_engine.routers.cross_sell import CrossSellCreateRequest, create_cross_sell


class _FakeRedis:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self._store.get(key) for key in keys]


class _FailIfCalledSession:
    def add(self, _obj: object) -> None:
        raise AssertionError("db session should not be used when true availability is zero")

    async def commit(self) -> None:
        raise AssertionError("db session should not commit when true availability is zero")

    async def refresh(self, _obj: object) -> None:
        raise AssertionError("db session should not refresh when true availability is zero")

    async def rollback(self) -> None:
        return None


class _StaticAvailabilityClient:
    def __init__(self, qty_by_item_id: dict[str, int]) -> None:
        self._qty_by_item_id = qty_by_item_id

    async def get_true_available_qty_map(
        self,
        item_ids: Iterable[str],
        *,
        raise_on_error: bool = False,  # noqa: ARG002
    ) -> dict[str, int]:
        return {str(item_id): int(self._qty_by_item_id.get(str(item_id), 0)) for item_id in item_ids}


@pytest.mark.asyncio
async def test_availability_client_calls_true_available_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"item_id": "item-123", "true_available_qty": 0}

    async def fake_get(self, url: str, *args, **kwargs):  # noqa: ANN001
        captured["url"] = url
        return _FakeResponse()

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = AvailabilityClient(base_url="http://localhost:8003")
    result = await client.get_true_available("item-123")

    assert captured["url"] == "http://localhost:8003/internal/items/item-123/true-available"
    assert result.item_id == "item-123"
    assert result.true_available_qty == 0


@pytest.mark.asyncio
async def test_catalog_pickable_items_filters_zero_true_available() -> None:
    item_id = str(uuid4())
    item_payload = {
        "item_id": item_id,
        "name": "Beans",
        "brand": "HomeSelect",
        "weight_per_unit": "kg",
        "expiry_date": "2026-12-31",
        "price_paise": 14500,
        "available_qty": 1,
        "is_active": True,
    }
    redis = _FakeRedis(
        store={
            "catalog:index": json.dumps([item_payload]),
            f"catalog:item:{item_id}": json.dumps(item_payload),
        }
    )
    availability_client = _StaticAvailabilityClient({item_id: 0})

    response = await get_pickable_items(redis_client=redis, availability_client=availability_client)  # type: ignore[arg-type]

    assert response["source"] == "redis"
    assert response["items"] == []


@pytest.mark.asyncio
async def test_combo_create_rejects_zero_true_available_items() -> None:
    payload = ComboCreateRequest(
        name="Combo A",
        description="Discounted pair",
        item_ids=["item-a"],
        combo_with_item_ids=["item-b"],
        discount_type="PERCENT",
        value=10,
    )
    availability_client = _StaticAvailabilityClient({"item-a": 1, "item-b": 0})

    with pytest.raises(HTTPException) as exc_info:
        await create_combo(
            payload=payload,
            db_session=_FailIfCalledSession(),  # type: ignore[arg-type]
            redis_client=None,  # type: ignore[arg-type]
            availability_client=availability_client,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "ITEM_TRUE_AVAILABILITY_ZERO"
    assert "item-b" in exc_info.value.detail["item_ids"]


@pytest.mark.asyncio
async def test_cross_sell_create_rejects_zero_true_available_items() -> None:
    source_item_id = uuid4()
    target_item_id = uuid4()
    payload = CrossSellCreateRequest(source_item_id=source_item_id, target_item_ids=[target_item_id], priority=0)
    availability_client = _StaticAvailabilityClient({str(source_item_id): 1, str(target_item_id): 0})

    with pytest.raises(HTTPException) as exc_info:
        await create_cross_sell(
            payload=payload,
            db_session=_FailIfCalledSession(),  # type: ignore[arg-type]
            availability_client=availability_client,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "ITEM_TRUE_AVAILABILITY_ZERO"
    assert str(target_item_id) in exc_info.value.detail["item_ids"]
