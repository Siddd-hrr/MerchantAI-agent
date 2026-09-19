from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from services.offer_engine.main import app
from shared.models.cross_sell import CrossSellPreference
from shared.models.offer import Offer


@pytest.mark.asyncio
async def test_list_and_terminate_saved_offer(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.offer_engine.routers import offers as offers_router
    from services.offer_engine.routers import common as common_router

    offer_id = uuid4()

    class FakeResult:
        def __init__(self, value):
            self._value = value

        def scalars(self):
            return self

        def all(self):
            return self._value if isinstance(self._value, list) else [self._value]

        def scalar_one_or_none(self):
            return self._value

    class FakeSession:
        def __init__(self):
            self.offer = Offer(
                id=offer_id,
                offer_type="DISCOUNT",
                name="Test 10%",
                description="demo",
                item_ids=["item-1"],
                condition={},
                discount_type="PERCENT",
                value=10,
                is_active=True,
            )
            self.committed = False

        async def execute(self, _stmt):
            # list vs get-by-id — return list for list endpoint path via all(),
            # and single for terminate via scalar_one_or_none.
            return FakeResult([self.offer] if self.offer.is_active else [])

        async def commit(self):
            self.committed = True

        async def refresh(self, obj):
            return None

        async def rollback(self):
            return None

    session = FakeSession()

    # Patch terminate path to return the single offer object
    original_execute = session.execute

    async def execute_smart(_stmt):
        # Heuristic: terminate uses scalar_one_or_none; list uses .all()
        class DualResult:
            def scalars(self):
                return self

            def all(self):
                return [session.offer] if session.offer.is_active else []

            def scalar_one_or_none(self):
                return session.offer

        return DualResult()

    session.execute = execute_smart  # type: ignore[method-assign]

    async def fake_session_dep():
        yield session

    async def fake_redis_dep():
        class R:
            async def get(self, *_a, **_k):
                return None

            async def set(self, *_a, **_k):
                return True

        yield R()

    async def fake_sync(*_a, **_k):
        return {"success": True, "synced_item_ids": ["item-1"], "errors": []}

    app.dependency_overrides[common_router.get_offer_session_dependency] = fake_session_dep
    app.dependency_overrides[common_router.get_offer_redis_dependency] = fake_redis_dep
    monkeypatch.setattr(offers_router, "sync_offer_item_cache", fake_sync)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/offers/saved")
        assert listed.status_code == 200
        body = listed.json()
        assert body["count"] == 1
        assert body["offers"][0]["name"] == "Test 10%"

        deleted = await client.delete(f"/offers/{offer_id}")
        assert deleted.status_code == 200
        assert deleted.json()["offer"]["is_active"] is False
        assert session.offer.is_active is False

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_and_terminate_cross_sell(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.offer_engine.routers import common as common_router

    pref_id = uuid4()
    source_id = uuid4()

    class FakeSession:
        def __init__(self):
            self.pref = CrossSellPreference(
                id=pref_id,
                source_item_id=source_id,
                target_item_ids=[str(uuid4())],
                priority=0,
                is_active=True,
            )

        async def execute(self, _stmt):
            class DualResult:
                def scalars(self_inner):
                    return self_inner

                def all(self_inner):
                    return [self.pref] if self.pref.is_active else []

                def scalar_one_or_none(self_inner):
                    return self.pref

            return DualResult()

        async def commit(self):
            return None

        async def refresh(self, _obj):
            return None

        async def rollback(self):
            return None

    session = FakeSession()

    async def fake_session_dep():
        yield session

    app.dependency_overrides[common_router.get_offer_session_dependency] = fake_session_dep

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/offers/cross-sell")
        assert listed.status_code == 200
        assert listed.json()["count"] == 1

        deleted = await client.delete(f"/offers/cross-sell/{pref_id}")
        assert deleted.status_code == 200
        assert deleted.json()["cross_sell_preference"]["is_active"] is False
        assert session.pref.is_active is False

    app.dependency_overrides.clear()
