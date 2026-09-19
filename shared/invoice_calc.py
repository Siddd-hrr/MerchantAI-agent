from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InvoiceTotals:
    subtotal_paise: int
    discount_paise: int
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    tax_paise: int
    shipping_paise: int
    total_paise: int


def compute_invoice_totals(
    *,
    subtotal_paise: int,
    discount_paise: int,
    gst_rate_bps: int = 500,
    shipping_paise: int = 4000,
    free_shipping_min_paise: int = 50000,
) -> InvoiceTotals:
    subtotal_paise = max(int(subtotal_paise), 0)
    discount_paise = max(int(discount_paise), 0)
    taxable_paise = max(subtotal_paise - discount_paise, 0)
    half_rate_bps = max(int(gst_rate_bps), 0) // 2
    cgst_paise = taxable_paise * half_rate_bps // 10000
    sgst_paise = taxable_paise * half_rate_bps // 10000
    tax_paise = cgst_paise + sgst_paise
    shipping = (
        0
        if taxable_paise >= max(int(free_shipping_min_paise), 0)
        else max(int(shipping_paise), 0)
    )
    total_paise = taxable_paise + tax_paise + shipping
    return InvoiceTotals(
        subtotal_paise=subtotal_paise,
        discount_paise=discount_paise,
        taxable_paise=taxable_paise,
        cgst_paise=cgst_paise,
        sgst_paise=sgst_paise,
        tax_paise=tax_paise,
        shipping_paise=shipping,
        total_paise=total_paise,
    )
