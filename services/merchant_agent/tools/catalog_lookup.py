from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.merchant_agent.catalog_service import CatalogService


class CatalogLookupTool:
    """Thin wrapper around CatalogService for graph tool execution."""

    def __init__(self, catalog_service: CatalogService) -> None:
        self._catalog_service = catalog_service

    async def resolve_item(
        self,
        db_session: AsyncSession,
        *,
        item_name: str,
        brand: str | None = None,
    ) -> list[dict[str, Any]]:
        matches = await self._catalog_service.resolve_item(db_session, item_name=item_name, brand=brand)
        return [match.model_dump() for match in matches]

    async def get_item_by_id(self, db_session: AsyncSession, item_id: str) -> dict[str, Any] | None:
        return await self._catalog_service.get_item_by_id(db_session, item_id)

    async def find_alternatives(
        self,
        db_session: AsyncSession,
        *,
        item_name: str,
        excluded_brand: str,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        alternatives = await self._catalog_service.find_alternatives(
            db_session,
            item_name=item_name,
            excluded_brand=excluded_brand,
            limit=limit,
        )
        return [alt.model_dump() for alt in alternatives]
