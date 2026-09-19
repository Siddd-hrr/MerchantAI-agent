from __future__ import annotations

from fastapi import APIRouter

from services.reservation_service.reservation_service import ReservationService
from services.reservation_service.schemas import (
    ReservationSubmitInvoiceRequest,
    ReservationSubmitInvoiceResponse,
)


def build_router(service: ReservationService) -> APIRouter:
    router = APIRouter(tags=["reservation"])

    @router.post(
        "/reservation/submit-invoice",
        response_model=ReservationSubmitInvoiceResponse,
        response_model_exclude_none=True,
    )
    async def submit_invoice(payload: ReservationSubmitInvoiceRequest) -> ReservationSubmitInvoiceResponse:
        invoice_id: str
        line_items: list[dict[str, object]]
        invoice_payload: dict[str, object] | None = None

        if payload.invoice is not None:
            invoice_id = str(payload.invoice.order_id)
            line_items = [
                {"item_id": str(line.item_id), "qty": int(line.qty)}
                for line in payload.invoice.line_items
            ]
            invoice_payload = payload.invoice.model_dump(mode="json")
        else:
            invoice_id = str(payload.invoice_id)
            line_items = [
                {"item_id": str(line.item_id), "qty": int(line.qty)}
                for line in payload.line_items
            ]

        result = await service.reserve(
            invoice_id=invoice_id,
            line_items=line_items,
            invoice_payload=invoice_payload,
        )
        return ReservationSubmitInvoiceResponse.model_validate(result)

    return router
