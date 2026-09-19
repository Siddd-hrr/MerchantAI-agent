from __future__ import annotations

from datetime import date
from uuid import uuid4

import pandas as pd
import pytest

from services.merchant_admin.routers import upload
from shared.models.item import Item


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


class FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


def test_validate_catalog_rows_rejects_invalid_rows() -> None:
    dataframe = pd.DataFrame(
        [
            {
                "name": "Milk",
                "brand": "",
                "weight_per_unit": "L",
                "price_paise": 6500,
                "quantity_available": 2,
                "expiry_date": "2026-12-31",
            },
            {
                "name": "Beans",
                "brand": "FreshFarm",
                "weight_per_unit": "kg",
                "price_paise": -1200,
                "quantity_available": 8,
                "expiry_date": "2026-12-31",
            },
            {
                "name": "Rice",
                "brand": "Fortune",
                "weight_per_unit": "kg",
                "price_paise": "abc",
                "quantity_available": 4,
                "expiry_date": "2026-12-31",
            },
        ]
    )

    accepted, rejected = upload.validate_catalog_rows(dataframe)

    assert accepted == []
    assert len(rejected) == 3
    assert rejected[0]["reason"] == "brand is required"
    assert "cannot be negative" in rejected[1]["reason"]
    assert "must be an integer" in rejected[2]["reason"]


@pytest.mark.asyncio
async def test_ingest_catalog_dataframe_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    dataframe = pd.DataFrame(
        [
            {
                "name": "Milk",
                "brand": "Amul",
                "weight_per_unit": "L",
                "price_paise": 6500,
                "quantity_available": 3,
                "expiry_date": "2026-12-31",
            }
        ]
    )

    fake_item = Item(
        id=uuid4(),
        name="Milk",
        brand="Amul",
        weight_per_unit="L",
        price_paise=6500,
        quantity_available=3,
        expiry_date=date(2026, 12, 31),
        is_active=True,
    )
    session = FakeSession()
    redis = FakeRedis()
    rebuild_called = {"value": False}

    async def fake_upsert(_db_session, _rows):
        return 1, 0, [fake_item]

    async def fake_rebuild(_db_session, _redis_client, _ttl_seconds=None):
        rebuild_called["value"] = True
        return []

    monkeypatch.setattr(upload, "upsert_catalog_rows", fake_upsert)
    monkeypatch.setattr(upload, "rebuild_catalog_index_from_db", fake_rebuild)

    result = await upload.ingest_catalog_dataframe(session, redis, dataframe)

    assert result == {"inserted": 1, "updated": 0, "rejected": []}
    assert session.committed is True
    assert rebuild_called["value"] is True
    assert f"catalog:item:{fake_item.id}" in redis.store
