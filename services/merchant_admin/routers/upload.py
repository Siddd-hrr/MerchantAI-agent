from __future__ import annotations

import numbers
from dataclasses import dataclass
from collections.abc import AsyncGenerator
from datetime import date
from io import BytesIO
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.merchant_agent.catalog_service import (
    invalidate_catalog_items,
    rebuild_catalog_index_from_db,
    refresh_catalog_items,
)
from shared.catalog_fields import normalize_weight_per_unit, parse_expiry_date
from shared.db import get_db_session
from shared.models.item import Item
from shared.redis_client import close_redis_client, get_redis_client

router = APIRouter(tags=["admin-upload"])

REQUIRED_COLUMNS = [
    "name",
    "brand",
    "weight_per_unit",
    "price_paise",
    "quantity_available",
    "expiry_date",
]


@dataclass(slots=True)
class ValidatedUploadRow:
    row_number: int
    name: str
    brand: str
    weight_per_unit: str
    price_paise: int
    quantity_available: int
    expiry_date: date


async def get_redis_dependency() -> AsyncGenerator[Redis, None]:
    redis_client = get_redis_client()
    try:
        yield redis_client
    finally:
        await close_redis_client(redis_client)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return bool(pd.isna(value))


def _parse_non_negative_int(value: Any, *, field_name: str) -> int:
    if _is_blank(value):
        raise ValueError(f"{field_name} is required")

    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")

    if isinstance(value, numbers.Integral):
        parsed = value
    elif isinstance(value, numbers.Real):
        if not float(value).is_integer():
            raise ValueError(f"{field_name} must be an integer")
        parsed = int(value)
    elif isinstance(value, str):
        value = value.strip()
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an integer") from exc
    else:
        raise ValueError(f"{field_name} must be an integer")

    if parsed < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return int(parsed)


def parse_catalog_upload(file_name: str | None, raw_bytes: bytes) -> pd.DataFrame:
    normalized_name = (file_name or "").lower()
    stream = BytesIO(raw_bytes)
    if normalized_name.endswith(".csv"):
        return pd.read_csv(stream, dtype=object)
    if normalized_name.endswith(".xlsx"):
        return pd.read_excel(stream, dtype=object)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Only .csv and .xlsx uploads are supported.",
    )


def validate_catalog_rows(dataframe: pd.DataFrame) -> tuple[list[ValidatedUploadRow], list[dict[str, Any]]]:
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in dataframe.columns]
    if missing_columns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required columns: {', '.join(missing_columns)}",
        )

    accepted_rows: list[ValidatedUploadRow] = []
    rejected_rows: list[dict[str, Any]] = []

    for row_idx, row in enumerate(dataframe.to_dict(orient="records"), start=2):
        try:
            name_raw = row.get("name")
            brand_raw = row.get("brand")
            weight_raw = row.get("weight_per_unit")
            expiry_raw = row.get("expiry_date")

            if _is_blank(name_raw):
                raise ValueError("name is required")
            if _is_blank(brand_raw):
                raise ValueError("brand is required")
            if _is_blank(weight_raw):
                raise ValueError("weight_per_unit is required")
            if _is_blank(expiry_raw):
                raise ValueError("expiry_date is required")

            accepted_rows.append(
                ValidatedUploadRow(
                    row_number=row_idx,
                    name=str(name_raw).strip(),
                    brand=str(brand_raw).strip(),
                    weight_per_unit=normalize_weight_per_unit(str(weight_raw)),
                    price_paise=_parse_non_negative_int(row.get("price_paise"), field_name="price_paise"),
                    quantity_available=_parse_non_negative_int(
                        row.get("quantity_available"),
                        field_name="quantity_available",
                    ),
                    expiry_date=parse_expiry_date(expiry_raw),
                )
            )
        except ValueError as exc:
            rejected_rows.append({"row": row_idx, "reason": str(exc)})

    return accepted_rows, rejected_rows


async def upsert_catalog_rows(
    db_session: AsyncSession, rows: list[ValidatedUploadRow]
) -> tuple[int, int, list[Item]]:
    inserted = 0
    updated = 0
    touched_items: list[Item] = []

    for row in rows:
        existing = (
            await db_session.execute(
                select(Item).where(
                    func.lower(Item.name) == row.name.lower(),
                    func.lower(Item.brand) == row.brand.lower(),
                    Item.expiry_date == row.expiry_date,
                    func.lower(Item.weight_per_unit) == row.weight_per_unit.lower(),
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            item = Item(
                name=row.name,
                brand=row.brand,
                weight_per_unit=row.weight_per_unit,
                price_paise=row.price_paise,
                quantity_available=row.quantity_available,
                expiry_date=row.expiry_date,
                is_active=True,
            )
            db_session.add(item)
            await db_session.flush()
            inserted += 1
            touched_items.append(item)
            continue

        existing.quantity_available += row.quantity_available
        existing.price_paise = row.price_paise
        existing.is_active = True
        updated += 1
        touched_items.append(existing)

    if rows:
        await db_session.flush()
    return inserted, updated, touched_items


async def ingest_catalog_dataframe(
    db_session: AsyncSession, redis_client: Redis, dataframe: pd.DataFrame
) -> dict[str, Any]:
    valid_rows, rejected_rows = validate_catalog_rows(dataframe)
    inserted, updated, touched_items = await upsert_catalog_rows(db_session, valid_rows)
    await db_session.commit()

    # NOTE: No auth in this phase by design; this endpoint is intentionally open for local bootstrap.
    await invalidate_catalog_items(redis_client, [str(item.id) for item in touched_items])
    await refresh_catalog_items(redis_client, touched_items)
    await rebuild_catalog_index_from_db(db_session, redis_client)

    return {
        "inserted": inserted,
        "updated": updated,
        "rejected": rejected_rows,
    }


@router.post("/admin/items/upload")
async def upload_items_catalog(
    file: UploadFile = File(...),
    db_session: AsyncSession = Depends(get_db_session),
    redis_client: Redis = Depends(get_redis_dependency),
) -> dict[str, Any]:
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    dataframe = parse_catalog_upload(file.filename, payload)
    return await ingest_catalog_dataframe(db_session, redis_client, dataframe)
