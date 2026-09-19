from services.merchant_agent.display_format import (
    format_expiry,
    format_inr_paise,
    format_price_per_unit,
    format_stock_qty,
)


def test_format_inr_paise() -> None:
    assert format_inr_paise(14500) == "₹145.00"
    assert format_inr_paise(None) == "n/a"


def test_format_stock_qty_with_measure() -> None:
    assert format_stock_qty(18, "kg") == "18 in stock (kg)"
    assert format_stock_qty(10, None) == "10 in stock"


def test_format_price_per_unit() -> None:
    assert format_price_per_unit(6500, "L") == "₹65.00 per L"


def test_format_expiry() -> None:
    assert format_expiry("2026-12-31") == "exp. 31 Dec 2026"
