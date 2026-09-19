from __future__ import annotations

from datetime import date, datetime

ALLOWED_WEIGHT_UNITS = frozenset({"kg", "g", "L", "ml"})


def normalize_weight_per_unit(value: str) -> str:
    lowered = value.strip().lower()
    if lowered == "gm":
        return "g"
    if lowered == "l":
        return "L"
    if lowered in {"kg", "g", "ml"}:
        return lowered
    raise ValueError(f"weight_per_unit must be one of: {', '.join(sorted(ALLOWED_WEIGHT_UNITS))}")


def parse_expiry_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value is None:
        raise ValueError("expiry_date is required")
    text = str(value).strip()
    if not text:
        raise ValueError("expiry_date is required")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError("expiry_date must be YYYY-MM-DD") from exc


def expiry_date_to_str(value: date | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def is_expired(value: date | str | None, *, today: date | None = None) -> bool:
    if value is None:
        return False
    reference = today or date.today()
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return False
    return value < reference
