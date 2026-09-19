from __future__ import annotations

from typing import Any

from services.merchant_agent.display_format import format_inr_paise

_OFFER_TYPE_LABELS = {
    "DISCOUNT": "Discount",
    "COMBO": "Combo deal",
    "FESTIVAL_CAMPAIGN": "Festival campaign",
    "COUPON": "Coupon",
    "CROSS_SELL": "Cross-sell",
}

_OFFER_TYPE_ORDER = ("DISCOUNT", "COMBO", "FESTIVAL_CAMPAIGN", "COUPON", "CROSS_SELL")


def merge_offers(*offer_groups: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in offer_groups:
        for offer in group or []:
            if not isinstance(offer, dict):
                continue
            offer_id = str(offer.get("id") or "")
            if offer_id:
                merged[offer_id] = offer
    return list(merged.values())


def format_offer_value(offer: dict[str, Any]) -> str:
    discount_type = str(offer.get("discount_type", "")).upper()
    value = int(offer.get("value", 0))
    if discount_type in {"PERCENT", "CASHBACK"}:
        return f"{value}%"
    if discount_type == "FLAT":
        return format_inr_paise(value)
    return str(value)


def format_offer_bullet(offer: dict[str, Any]) -> str:
    offer_type = str(offer.get("offer_type", "")).upper()
    label = _OFFER_TYPE_LABELS.get(offer_type, offer_type.replace("_", " ").title() or "Offer")
    name = str(offer.get("name") or "").strip()
    description = str(offer.get("description") or "").strip()
    coupon = str(offer.get("coupon_code") or "").strip()
    festival = str(offer.get("festival_name") or "").strip()

    if description:
        body = description
    elif name:
        body = name
    else:
        body = label

    if offer_type == "COUPON" and coupon and coupon not in body:
        body = f"{body} (code: {coupon})"
    if festival and festival not in body:
        body = f"{body} ({festival})"

    return f"[{label}] {body}"


def format_surfaced_promotions(
    offers: list[dict[str, Any]] | None,
    campaigns: list[dict[str, Any]] | None = None,
) -> str:
    merged_list = merge_offers(offers, campaigns)
    if not merged_list:
        return ""

    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in _OFFER_TYPE_ORDER}
    grouped["OTHER"] = []
    for offer in merged_list:
        offer_type = str(offer.get("offer_type", "")).upper()
        bucket = offer_type if offer_type in grouped else "OTHER"
        grouped[bucket].append(offer)

    lines = ["💡 Promotions & deals you can unlock:", ""]
    for offer_type in _OFFER_TYPE_ORDER:
        for offer in grouped[offer_type]:
            lines.append(f"• {format_offer_bullet(offer)}")
    for offer in grouped["OTHER"]:
        lines.append(f"• {format_offer_bullet(offer)}")
    return "\n".join(lines)
