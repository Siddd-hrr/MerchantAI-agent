from __future__ import annotations

import pytest

from shared.invoice_calc import compute_invoice_totals


def test_compute_invoice_totals_with_shipping_and_gst() -> None:
    totals = compute_invoice_totals(
        subtotal_paise=5400,
        discount_paise=0,
        gst_rate_bps=500,
        shipping_paise=4000,
        free_shipping_min_paise=50000,
    )
    assert totals.subtotal_paise == 5400
    assert totals.discount_paise == 0
    assert totals.taxable_paise == 5400
    assert totals.cgst_paise == 135
    assert totals.sgst_paise == 135
    assert totals.tax_paise == 270
    assert totals.shipping_paise == 4000
    assert totals.total_paise == 9670


def test_compute_invoice_totals_free_shipping_above_threshold() -> None:
    totals = compute_invoice_totals(
        subtotal_paise=60000,
        discount_paise=0,
        gst_rate_bps=500,
        shipping_paise=4000,
        free_shipping_min_paise=50000,
    )
    assert totals.shipping_paise == 0
    assert totals.total_paise == 63000


def test_compute_invoice_totals_discount_cannot_go_negative() -> None:
    totals = compute_invoice_totals(
        subtotal_paise=1000,
        discount_paise=5000,
        gst_rate_bps=500,
        shipping_paise=4000,
        free_shipping_min_paise=50000,
    )
    assert totals.taxable_paise == 0
    assert totals.cgst_paise == 0
    assert totals.sgst_paise == 0
    assert totals.shipping_paise == 4000
    assert totals.total_paise == 4000


@pytest.mark.parametrize(
    ("subtotal", "discount", "expected_taxable"),
    [
        (35200, 2900, 32300),
    ],
)
def test_compute_invoice_totals_with_discount(subtotal: int, discount: int, expected_taxable: int) -> None:
    totals = compute_invoice_totals(
        subtotal_paise=subtotal,
        discount_paise=discount,
        gst_rate_bps=500,
        shipping_paise=4000,
        free_shipping_min_paise=50000,
    )
    assert totals.taxable_paise == expected_taxable
    assert totals.discount_paise == discount
