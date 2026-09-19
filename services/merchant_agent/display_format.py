from __future__ import annotations


def format_inr_paise(paise: int | None) -> str:
    if paise is None:
        return "n/a"
    return f"₹{(int(paise) / 100):.2f}"


def format_stock_qty(available_qty: int | None, weight_per_unit: str | None = None) -> str:
    qty = int(available_qty or 0)
    measure = (weight_per_unit or "").strip()
    if measure:
        return f"{qty} in stock ({measure})"
    return f"{qty} in stock"


def format_price_per_unit(price_paise: int | None, weight_per_unit: str | None = None) -> str:
    price_txt = format_inr_paise(price_paise)
    measure = (weight_per_unit or "").strip()
    if measure:
        return f"{price_txt} per {measure}"
    return f"{price_txt} per unit"


def format_expiry(expiry_date: str | None) -> str:
    if not expiry_date:
        return ""
    try:
        from datetime import date

        parsed = date.fromisoformat(str(expiry_date)[:10])
        return f"exp. {parsed.strftime('%d %b %Y')}"
    except ValueError:
        return f"exp. {expiry_date}"
