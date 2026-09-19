from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.invoice_calc import compute_invoice_totals
from shared.models.order import Order
from shared.models.offer_applied_log import OfferAppliedLog
from shared.schemas.invoice import AcceptedOffer, Invoice, InvoiceLineItem

from services.merchant_agent.memory_store import MemoryStore


class InvoiceService:
    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory_store = memory_store

    async def generate_invoice(
        self,
        db_session: AsyncSession,
        *,
        session_id: str,
        consumer_agent_id: str,
        mandate_verified: bool,
        line_items: list[dict[str, Any]],
        customer_name: str | None,
        address: str | None,
        phone: str | None,
        accepted_offers: list[dict[str, Any]] | None = None,
        order_id: str | None = None,
    ) -> Invoice:
        settings = get_settings()
        invoice_items: list[InvoiceLineItem] = []
        subtotal_paise = 0
        for item in line_items:
            qty = int(item["qty"])
            unit_price_paise = int(item["unit_price_paise"])
            line_total_paise = qty * unit_price_paise
            subtotal_paise += line_total_paise
            weight = item.get("weight_per_unit")
            invoice_items.append(
                InvoiceLineItem(
                    item_id=str(item["item_id"]),
                    name=item["item_name"],
                    brand=item["brand"],
                    qty=qty,
                    unit_price_paise=unit_price_paise,
                    line_total_paise=line_total_paise,
                    weight_per_unit=str(weight) if weight else None,
                )
            )

        normalized_order_id = UUID(order_id) if order_id else uuid4()
        accepted_offers = accepted_offers or []
        discount_paise = sum(int(offer.get("amount_saved_paise", 0)) for offer in accepted_offers)
        totals = compute_invoice_totals(
            subtotal_paise=subtotal_paise,
            discount_paise=discount_paise,
            gst_rate_bps=settings.invoice_gst_rate_bps,
            shipping_paise=settings.invoice_shipping_paise,
            free_shipping_min_paise=settings.invoice_free_shipping_min_paise,
        )
        issued_at = datetime.now(timezone.utc).isoformat()

        db_session.add(
            Order(
                id=normalized_order_id,
                consumer_agent_id=consumer_agent_id,
                session_id=session_id,
                status="INVOICED",
                line_items=[
                    {
                        "item_id": li.item_id,
                        "name": li.name,
                        "brand": li.brand,
                        "qty": li.qty,
                        "unit_price_paise": li.unit_price_paise,
                        "line_total_paise": li.line_total_paise,
                        "weight_per_unit": li.weight_per_unit,
                    }
                    for li in invoice_items
                ],
                customer_name=customer_name,
                address=address,
                phone_number=phone,
                mandate_verified=mandate_verified,
                total_paise=totals.total_paise,
            )
        )
        await db_session.flush()
        for offer in accepted_offers:
            offer_id = offer.get("id")
            if not offer_id:
                continue
            try:
                normalized_offer_id = UUID(str(offer_id))
            except ValueError:
                continue
            db_session.add(
                OfferAppliedLog(
                    order_id=normalized_order_id,
                    offer_id=normalized_offer_id,
                    description=str(offer.get("description", "")),
                    amount_saved_paise=int(offer.get("amount_saved_paise", 0)),
                )
            )

        await self.memory_store.append_audit(
            db_session,
            session_id=session_id,
            actor="merchant_agent",
            action="INVOICE_GENERATED",
            detail={
                "order_id": str(normalized_order_id),
                "line_items": [item.model_dump() for item in invoice_items],
                "subtotal_paise": totals.subtotal_paise,
                "discount_paise": totals.discount_paise,
                "taxable_paise": totals.taxable_paise,
                "cgst_paise": totals.cgst_paise,
                "sgst_paise": totals.sgst_paise,
                "tax_paise": totals.tax_paise,
                "shipping_paise": totals.shipping_paise,
                "total_paise": totals.total_paise,
                "accepted_offers": accepted_offers,
                "customer_name": customer_name,
                "address": address,
                "phone": phone,
            },
        )

        return Invoice(
            order_id=str(normalized_order_id),
            session_id=session_id,
            issued_at=issued_at,
            merchant_name=settings.merchant_name,
            customer_name=customer_name,
            address=address,
            phone_number=phone,
            line_items=invoice_items,
            subtotal_paise=totals.subtotal_paise,
            discount_paise=totals.discount_paise,
            taxable_paise=totals.taxable_paise,
            cgst_paise=totals.cgst_paise,
            sgst_paise=totals.sgst_paise,
            tax_paise=totals.tax_paise,
            shipping_paise=totals.shipping_paise,
            total_paise=totals.total_paise,
            accepted_offers=[
                AcceptedOffer(
                    offer_id=str(offer.get("id", "")),
                    description=str(offer.get("description", "")),
                    amount_saved_paise=int(offer.get("amount_saved_paise", 0)),
                )
                for offer in accepted_offers
                if offer.get("id")
            ],
        )
