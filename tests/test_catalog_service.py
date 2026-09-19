from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.merchant_agent.catalog_service import (
    CATALOG_INDEX_KEY,
    CatalogService,
    catalog_item_key,
    item_to_catalog_payload,
    pick_best_match_payload,
)
from shared.models.item import Item


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        if ex is not None:
            self.ttl[key] = ex

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


class FakeScalarResult:
    def __init__(self, *, one: Item | None = None, many: list[Item] | None = None) -> None:
        self.one = one
        self.many = many or []

    def scalar_one_or_none(self) -> Item | None:
        return self.one

    def scalars(self) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: self.many)


class FakeDbSession:
    def __init__(self, results: list[FakeScalarResult]) -> None:
        self._results = list(results)
        self.execute_calls = 0

    async def execute(self, _statement):
        self.execute_calls += 1
        return self._results.pop(0)


def build_item(
    name: str,
    brand: str,
    *,
    weight_per_unit: str = "L",
    qty: int = 5,
    price: int = 6200,
    expiry_date: date | None = None,
) -> Item:
    return Item(
        id=uuid4(),
        name=name,
        brand=brand,
        weight_per_unit=weight_per_unit,
        price_paise=price,
        quantity_available=qty,
        expiry_date=expiry_date or date(2026, 12, 31),
        is_active=True,
    )


@pytest.mark.asyncio
async def test_get_by_id_prefers_redis_cache() -> None:
    item = build_item("Milk", "Amul")
    redis = FakeRedis()
    redis.store[catalog_item_key(str(item.id))] = json.dumps(item_to_catalog_payload(item))
    service = CatalogService(redis_client=redis)
    session = FakeDbSession(results=[])

    result = await service.get_by_id(session, str(item.id))

    assert result is not None
    assert result["name"] == "Milk"
    assert session.execute_calls == 0


@pytest.mark.asyncio
async def test_get_by_id_falls_back_to_db_and_warms_cache() -> None:
    item = build_item("Beans", "FreshFarm", weight_per_unit="kg", qty=12, price=14500)
    redis = FakeRedis()
    service = CatalogService(redis_client=redis)
    session = FakeDbSession(results=[FakeScalarResult(one=item)])

    result = await service.get_by_id(session, str(item.id))

    assert result is not None
    assert result["brand"] == "FreshFarm"
    assert catalog_item_key(str(item.id)) in redis.store
    assert session.execute_calls == 1


@pytest.mark.asyncio
async def test_search_by_name_uses_index_when_present() -> None:
    milk_a = build_item("Milk", "Amul", qty=1, price=6500)
    milk_b = build_item("Milk", "DairyGold", qty=10, price=6200)
    redis = FakeRedis()
    redis.store[CATALOG_INDEX_KEY] = json.dumps([item_to_catalog_payload(milk_a), item_to_catalog_payload(milk_b)])
    service = CatalogService(redis_client=redis)
    session = FakeDbSession(results=[])

    results = await service.search_by_name(session, item_name="milk", brand="DairyGold")

    assert len(results) == 1
    assert results[0].brand == "DairyGold"
    assert session.execute_calls == 0


@pytest.mark.asyncio
async def test_search_by_name_matches_brand_embedded_in_query() -> None:
    milk_a = build_item("Milk", "Amul", qty=1, price=6500)
    milk_b = build_item("Milk", "DairyGold", qty=10, price=6200)
    redis = FakeRedis()
    redis.store[CATALOG_INDEX_KEY] = json.dumps([item_to_catalog_payload(milk_a), item_to_catalog_payload(milk_b)])
    service = CatalogService(redis_client=redis)
    session = FakeDbSession(results=[])

    results = await service.search_by_name(session, item_name="Amul milk", brand="Amul")

    assert len(results) == 1
    assert results[0].brand == "Amul"


@pytest.mark.asyncio
async def test_search_by_name_fuzzy_typo_and_empty_index_fallback() -> None:
    milk = build_item("Milk", "DairyGold", qty=10, price=6200)
    redis = FakeRedis()
    redis.store[CATALOG_INDEX_KEY] = json.dumps([])
    service = CatalogService(redis_client=redis)
    session = FakeDbSession(results=[FakeScalarResult(many=[milk])])

    results = await service.search_by_name(session, item_name="Millk", brand="DairyGold")

    assert len(results) == 1
    assert results[0].brand == "DairyGold"
    assert session.execute_calls == 1


def test_pick_best_match_payload_uses_fefo_for_same_measure() -> None:
    payloads = [
        {
            "item_id": "a",
            "brand": "FreshFarm",
            "name": "Beans",
            "weight_per_unit": "kg",
            "expiry_date": "2026-12-31",
            "available_qty": 5,
        },
        {
            "item_id": "b",
            "brand": "FreshFarm",
            "name": "Beans",
            "weight_per_unit": "kg",
            "expiry_date": "2026-06-30",
            "available_qty": 8,
        },
    ]
    best = pick_best_match_payload(payloads, requested_qty=2)
    assert best is not None
    assert best["item_id"] == "b"


def test_pick_best_match_payload_returns_none_for_different_brands() -> None:
    payloads = [
        {"item_id": "a", "brand": "DairyGold", "name": "Milk", "weight_per_unit": "L", "expiry_date": "2026-12-31", "available_qty": 25},
        {"item_id": "b", "brand": "Amul", "name": "Milk", "weight_per_unit": "L", "expiry_date": "2026-12-31", "available_qty": 1},
    ]
    assert pick_best_match_payload(payloads) is None


def test_pick_best_match_payload_returns_none_for_different_measures() -> None:
    payloads = [
        {"item_id": "a", "weight_per_unit": "kg", "expiry_date": "2026-12-31", "available_qty": 5},
        {"item_id": "b", "weight_per_unit": "g", "expiry_date": "2026-12-31", "available_qty": 8},
    ]
    assert pick_best_match_payload(payloads) is None


@pytest.mark.asyncio
async def test_alternatives_same_name_filters_brand_and_stock() -> None:
    primary = build_item("Beans", "HomeSelect", weight_per_unit="kg", qty=0, price=13800)
    alt_one = build_item("Beans", "FreshFarm", weight_per_unit="kg", qty=8, price=14500)
    alt_two = build_item("Kidney Beans", "Tata Sampann", weight_per_unit="g", qty=6, price=11500)
    redis = FakeRedis()
    redis.store[CATALOG_INDEX_KEY] = json.dumps(
        [item_to_catalog_payload(primary), item_to_catalog_payload(alt_one), item_to_catalog_payload(alt_two)]
    )
    service = CatalogService(redis_client=redis)
    session = FakeDbSession(results=[])

    results = await service.alternatives_same_name(
        session,
        item_name="Beans",
        exclude_brand="HomeSelect",
        limit=3,
    )

    assert [result.brand for result in results] == ["FreshFarm", "Tata Sampann"]
