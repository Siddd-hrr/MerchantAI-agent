from __future__ import annotations

from typing import Any

import httpx


class ReservationClient:
    def __init__(self, reservation_service_url: str, *, timeout: float = 20.0) -> None:
        self._base_url = reservation_service_url.rstrip("/")
        self._timeout = timeout

    async def submit_invoice(self, reservation_payload: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any]
        if isinstance(reservation_payload.get("invoice"), dict):
            inner_invoice = dict(reservation_payload["invoice"])
            invoice_id = str(
                reservation_payload.get("invoice_id")
                or inner_invoice.get("invoice_id")
                or inner_invoice.get("order_id")
                or ""
            ).strip()
            line_items = reservation_payload.get("line_items") or inner_invoice.get("line_items") or []
            payload = {"invoice": inner_invoice}
            if invoice_id and line_items:
                payload = {"invoice_id": invoice_id, "line_items": line_items, "invoice": inner_invoice}
        else:
            invoice_id = str(
                reservation_payload.get("invoice_id") or reservation_payload.get("order_id") or ""
            ).strip()
            line_items = reservation_payload.get("line_items") or []
            if invoice_id and line_items:
                payload = {"invoice_id": invoice_id, "line_items": line_items}
            else:
                payload = {"invoice": reservation_payload}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base_url}/reservation/submit-invoice", json=payload)
            response.raise_for_status()
            return response.json()
