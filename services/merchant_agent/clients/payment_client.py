from __future__ import annotations

from typing import Any

import httpx


class PaymentClient:
    def __init__(self, payment_service_url: str, *, timeout: float = 20.0) -> None:
        self._base_url = payment_service_url.rstrip("/")
        self._timeout = timeout

    async def create_payment_link(
        self,
        *,
        merchant_id: str,
        session_id: str | None,
        invoice_id: str,
        amount_paise: int,
        customer_name: str | None,
        phone: str | None,
        description: str | None,
    ) -> dict[str, Any]:
        payload = {
            "merchant_id": merchant_id,
            "session_id": session_id,
            "invoice_id": invoice_id,
            "amount_paise": amount_paise,
            "customer_name": customer_name,
            "customer_phone": phone,
            "description": description,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base_url}/payment/create-link", json=payload)
            if response.status_code >= 400:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                error = body.get("error", {}) if isinstance(body, dict) else {}
                code = str(error.get("code") or "PAYMENT_LINK_CREATE_HTTP_ERROR")
                message = str(error.get("message") or response.text or "Payment create-link failed.")
                return {"success": False, "error": {"code": code, "message": message}}
            return response.json()

    async def cancel_payment_link(self, *, merchant_id: str, invoice_id: str) -> dict[str, Any]:
        payload = {"merchant_id": merchant_id, "invoice_id": invoice_id}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base_url}/payment/cancel-link", json=payload)
            response.raise_for_status()
            return response.json()
