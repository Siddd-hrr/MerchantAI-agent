from __future__ import annotations

import json
from datetime import date
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.catalog_fields import expiry_date_to_str, is_expired
from shared.config import get_settings
from shared.models.item import Item
from shared.redis_client import get_redis_client
from shared.schemas.catalog import CatalogSuggestion

CATALOG_INDEX_KEY = "catalog:index"


def catalog_item_key(item_id: str) -> str:
    return f"catalog:item:{item_id}"


def item_to_catalog_payload(item: Item) -> dict[str, Any]:
    return {
        "item_id": str(item.id),
        "name": item.name,
        "brand": item.brand,
        "weight_per_unit": item.weight_per_unit,
        "expiry_date": expiry_date_to_str(item.expiry_date),
        "price_paise": int(item.price_paise),
        "available_qty": int(item.quantity_available),
        "is_active": bool(item.is_active),
    }


async def invalidate_catalog_items(redis_client: Redis, item_ids: list[str]) -> None:
    for item_id in item_ids:
        await redis_client.delete(catalog_item_key(item_id))


async def refresh_catalog_items(
    redis_client: Redis, items: list[Item], ttl_seconds: int | None = None
) -> list[dict[str, Any]]:
    settings = get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else settings.catalog_cache_ttl_seconds
    payloads: list[dict[str, Any]] = []
    for item in items:
        payload = item_to_catalog_payload(item)
        payloads.append(payload)
        await redis_client.set(catalog_item_key(payload["item_id"]), json.dumps(payload), ex=ttl)
    return payloads


async def warm_catalog_cache(
    redis_client: Redis,
    items: list[Item],
    ttl_seconds: int | None = None,
    *,
    index_key: str = CATALOG_INDEX_KEY,
) -> list[dict[str, Any]]:
    payloads = await refresh_catalog_items(redis_client, items, ttl_seconds)
    settings = get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else settings.catalog_cache_ttl_seconds
    await redis_client.set(index_key, json.dumps(payloads), ex=ttl)
    return payloads


async def rebuild_catalog_index_from_db(
    db_session: AsyncSession, redis_client: Redis, ttl_seconds: int | None = None
) -> list[dict[str, Any]]:
    items = (
        await db_session.execute(
            select(Item).where(Item.is_active.is_(True)).order_by(Item.name.asc(), Item.brand.asc())
        )
    ).scalars().all()
    return await warm_catalog_cache(redis_client, list(items), ttl_seconds)


def _normalize_token(value: str) -> str:
    return "".join(ch for ch in value.strip().lower() if ch.isalnum())


def _tokens(value: str) -> list[str]:
    return [token for token in "".join(ch if ch.isalnum() else " " for ch in value.lower()).split() if token]


def _fuzzy_contains(haystack: str, needle: str) -> bool:
    """True when needle is in haystack, or close for small typos (edit distance <= 1)."""
    if not needle:
        return True
    if needle in haystack:
        return True
    if abs(len(haystack) - len(needle)) > 1 and needle not in haystack:
        pass
    if len(needle) <= 2:
        return needle in haystack
    if abs(len(haystack) - len(needle)) > 1:
        return False
    prev = list(range(len(needle) + 1))
    for i, ch_h in enumerate(haystack, start=1):
        curr = [i]
        for j, ch_n in enumerate(needle, start=1):
            cost = 0 if ch_h == ch_n else 1
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1] <= 1


def _payload_is_active(payload: dict[str, Any]) -> bool:
    return bool(payload.get("is_active", True))


def _filter_non_expired(payloads: list[dict[str, Any]], *, today: date | None = None) -> list[dict[str, Any]]:
    return [payload for payload in payloads if not is_expired(payload.get("expiry_date"), today=today)]


def pick_best_match_payload(
    payloads: list[dict[str, Any]],
    *,
    requested_qty: int | None = None,
) -> dict[str, Any] | None:
    if not payloads:
        return None
    if len(payloads) == 1:
        return payloads[0]

    weights = {str(payload.get("weight_per_unit", "")).lower() for payload in payloads}
    if len(weights) > 1:
        return None

    brands = {str(payload.get("brand", "")).strip().lower() for payload in payloads if str(payload.get("brand", "")).strip()}
    if len(brands) > 1:
        return None

    qty_needed = int(requested_qty or 1)

    def sort_key(payload: dict[str, Any]) -> tuple[str, int]:
        expiry = str(payload.get("expiry_date", "9999-12-31"))
        stock = int(payload.get("available_qty", 0))
        has_stock = 0 if stock >= qty_needed else 1
        return (has_stock, expiry)

    return sorted(payloads, key=sort_key)[0]


class CatalogService:
    def __init__(self, redis_client: Redis | None = None) -> None:
        self.settings = get_settings()
        self.redis = redis_client or get_redis_client()

    async def _load_index(self) -> list[dict[str, Any]] | None:
        raw = await self.redis.get(CATALOG_INDEX_KEY)
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, list) or len(parsed) == 0:
            return None
        return parsed

    @staticmethod
    def _to_suggestion(payload: dict[str, Any]) -> CatalogSuggestion:
        return CatalogSuggestion(
            item_id=payload["item_id"],
            name=payload["name"],
            brand=payload["brand"],
            price_paise=int(payload["price_paise"]),
            available_qty=int(payload["available_qty"]),
            weight_per_unit=str(payload.get("weight_per_unit", "")),
            expiry_date=str(payload.get("expiry_date", "")),
        )

    @staticmethod
    def _payload_matches(
        payload: dict[str, Any],
        *,
        item_name: str,
        brand: str | None,
    ) -> bool:
        name = str(payload.get("name", "")).lower()
        payload_brand = str(payload.get("brand", "")).lower()
        query_tokens = _tokens(item_name)
        brand_norm = _normalize_token(brand) if brand else None

        if brand_norm and _normalize_token(payload_brand) != brand_norm:
            return False

        product_tokens = [
            tok
            for tok in query_tokens
            if not brand_norm or _normalize_token(tok) != brand_norm
        ]
        catalog_brand_norm = _normalize_token(payload_brand)
        if not brand_norm and catalog_brand_norm:
            stripped = [tok for tok in product_tokens if _normalize_token(tok) != catalog_brand_norm]
            if stripped:
                product_tokens = stripped
        if not product_tokens:
            product_tokens = query_tokens

        name_tokens = _tokens(name)
        if not product_tokens:
            return False

        for token in product_tokens:
            token_norm = _normalize_token(token)
            if not token_norm:
                continue
            if token_norm in _normalize_token(name):
                return True
            if any(
                _fuzzy_contains(_normalize_token(nt), token_norm)
                or _fuzzy_contains(token_norm, _normalize_token(nt))
                for nt in name_tokens
            ):
                return True
        if _normalize_token(name) and _normalize_token(name) in _normalize_token(item_name):
            return True
        return False

    async def _search_payloads(
        self,
        db_session: AsyncSession,
        *,
        item_name: str,
        brand: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        index = await self._load_index()
        if index is not None:
            matched = [
                payload
                for payload in index
                if _payload_is_active(payload)
                and self._payload_matches(payload, item_name=item_name, brand=brand)
            ]
            return _filter_non_expired(matched)[:limit]

        rows = (
            await db_session.execute(
                select(Item)
                .where(Item.is_active.is_(True))
                .order_by(Item.name.asc(), Item.brand.asc())
            )
        ).scalars().all()
        payloads = await warm_catalog_cache(
            self.redis, list(rows), self.settings.catalog_cache_ttl_seconds
        )
        matched = [
            payload
            for payload in payloads
            if self._payload_matches(payload, item_name=item_name, brand=brand)
        ]
        return _filter_non_expired(matched)[:limit]

    async def get_by_id(self, db_session: AsyncSession, item_id: str) -> dict[str, Any] | None:
        cached = await self.redis.get(catalog_item_key(item_id))
        if cached:
            payload = json.loads(cached)
            if is_expired(payload.get("expiry_date")):
                return None
            return payload

        item = (
            await db_session.execute(select(Item).where(Item.id == item_id, Item.is_active.is_(True)))
        ).scalar_one_or_none()
        if item is None or is_expired(item.expiry_date):
            return None

        payloads = await refresh_catalog_items(self.redis, [item], self.settings.catalog_cache_ttl_seconds)
        return payloads[0]

    async def search_by_name(
        self,
        db_session: AsyncSession,
        *,
        item_name: str,
        brand: str | None = None,
        limit: int = 10,
    ) -> list[CatalogSuggestion]:
        matched = await self._search_payloads(
            db_session, item_name=item_name, brand=brand, limit=limit
        )
        return [self._to_suggestion(payload) for payload in matched]

    async def alternatives_same_name(
        self,
        db_session: AsyncSession,
        *,
        item_name: str,
        exclude_brand: str,
        limit: int = 3,
    ) -> list[CatalogSuggestion]:
        normalized_excluded_brand = exclude_brand.strip().lower()
        index = await self._load_index()
        if index is not None:
            matched = [
                payload
                for payload in index
                if _payload_is_active(payload)
                and self._payload_matches(payload, item_name=item_name, brand=None)
                and str(payload.get("brand", "")).lower() != normalized_excluded_brand
                and int(payload.get("available_qty", 0)) > 0
            ]
            matched = _filter_non_expired(matched)
            matched.sort(key=lambda payload: int(payload.get("available_qty", 0)), reverse=True)
            return [self._to_suggestion(payload) for payload in matched[:limit]]

        rows = (
            await db_session.execute(
                select(Item)
                .where(
                    Item.is_active.is_(True),
                    Item.brand != exclude_brand,
                    Item.quantity_available > 0,
                )
                .order_by(Item.quantity_available.desc())
            )
        ).scalars().all()
        item_list = list(rows)
        await warm_catalog_cache(self.redis, item_list, self.settings.catalog_cache_ttl_seconds)
        matched = [
            item_to_catalog_payload(item)
            for item in item_list
            if self._payload_matches(item_to_catalog_payload(item), item_name=item_name, brand=None)
            and str(item.brand).lower() != normalized_excluded_brand
            and not is_expired(item.expiry_date)
        ]
        return [self._to_suggestion(payload) for payload in matched[:limit]]

    async def resolve_item(
        self,
        db_session: AsyncSession,
        *,
        item_name: str,
        brand: str | None = None,
        requested_qty: int | None = None,
    ) -> list[CatalogSuggestion]:
        return await self.search_by_name(
            db_session,
            item_name=item_name,
            brand=brand,
            limit=10,
        )

    def pick_best_match(
        self,
        matches: list[CatalogSuggestion],
        *,
        requested_qty: int | None = None,
    ) -> CatalogSuggestion | None:
        payloads = [match.model_dump() for match in matches]
        best = pick_best_match_payload(payloads, requested_qty=requested_qty)
        if best is None:
            return None
        return self._to_suggestion(best)

    async def get_item_by_id(self, db_session: AsyncSession, item_id: str) -> dict[str, Any] | None:
        return await self.get_by_id(db_session, item_id)

    async def find_alternatives(
        self,
        db_session: AsyncSession,
        *,
        item_name: str,
        excluded_brand: str,
        limit: int = 3,
    ) -> list[CatalogSuggestion]:
        return await self.alternatives_same_name(
            db_session,
            item_name=item_name,
            exclude_brand=excluded_brand,
            limit=limit,
        )
