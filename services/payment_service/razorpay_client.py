from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from services.payment_service.credential_store import MerchantCredentials
from shared.config import get_settings


@dataclass(slots=True)
class PaymentLinkResult:
    payment_link_id: str
    payment_link_url: str


class RazorpayClientError(Exception):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RazorpayClientBase:
    async def create_link(
        self,
        *,
        merchant_id: str,
        invoice_id: str,
        session_id: str | None,
        amount_paise: int,
        customer_name: str | None,
        customer_phone: str | None,
        description: str | None,
    ) -> PaymentLinkResult:
        raise NotImplementedError

    async def cancel_link(self, *, payment_link_id: str) -> bool:
        raise NotImplementedError


class FakeRazorpayClient(RazorpayClientBase):
    async def create_link(
        self,
        *,
        merchant_id: str,
        invoice_id: str,
        session_id: str | None,
        amount_paise: int,
        customer_name: str | None,
        customer_phone: str | None,
        description: str | None,
    ) -> PaymentLinkResult:
        _ = merchant_id
        _ = session_id
        _ = amount_paise
        _ = customer_name
        _ = customer_phone
        _ = description
        return PaymentLinkResult(
            payment_link_id=f"plink_fake_{invoice_id}",
            payment_link_url=f"https://rzp.io/i/fake-{invoice_id}",
        )

    async def cancel_link(self, *, payment_link_id: str) -> bool:
        _ = payment_link_id
        return True


class RealRazorpayClient(RazorpayClientBase):
    def __init__(self, credentials: MerchantCredentials) -> None:
        self._credentials = credentials

    async def create_link(
        self,
        *,
        merchant_id: str,
        invoice_id: str,
        session_id: str | None,
        amount_paise: int,
        customer_name: str | None,
        customer_phone: str | None,
        description: str | None,
    ) -> PaymentLinkResult:
        settings = get_settings()
        expire_by = int(
            (
                datetime.now(timezone.utc)
                + timedelta(seconds=int(settings.payment_link_ttl_seconds))
            ).timestamp()
        )
        payload = {
            "amount": int(amount_paise),
            "currency": "INR",
            "reference_id": invoice_id,
            "description": description or f"Invoice {invoice_id}",
            "expire_by": expire_by,
            "notes": {
                "invoice_id": invoice_id,
                "session_id": session_id or "",
                "merchant_id": merchant_id,
            },
        }
        if customer_name:
            payload["customer"] = {"name": customer_name}
            if customer_phone:
                payload["customer"]["contact"] = customer_phone
        elif customer_phone:
            payload["customer"] = {"contact": customer_phone}
        async with httpx.AsyncClient(
            auth=(self._credentials.key_id, self._credentials.key_secret),
            timeout=20.0,
        ) as client:
            try:
                response = await client.post("https://api.razorpay.com/v1/payment_links", json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                message = "Razorpay returned an invalid response."
                try:
                    body = exc.response.json()
                    error_obj = body.get("error") if isinstance(body, dict) else None
                    if isinstance(error_obj, dict) and error_obj.get("description"):
                        message = str(error_obj["description"])
                except ValueError:
                    pass
                raise RazorpayClientError(code="RAZORPAY_CREATE_LINK_FAILED", message=message) from exc
            except httpx.RequestError as exc:
                raise RazorpayClientError(
                    code="RAZORPAY_NETWORK_ERROR",
                    message="Unable to reach Razorpay.",
                ) from exc
        body = response.json()
        return PaymentLinkResult(
            payment_link_id=str(body.get("id", "")),
            payment_link_url=str(body.get("short_url", "")),
        )

    async def cancel_link(self, *, payment_link_id: str) -> bool:
        async with httpx.AsyncClient(
            auth=(self._credentials.key_id, self._credentials.key_secret),
            timeout=20.0,
        ) as client:
            response = await client.post(f"https://api.razorpay.com/v1/payment_links/{payment_link_id}/cancel")
            response.raise_for_status()
        return True


def get_razorpay_client(credentials: MerchantCredentials | None) -> RazorpayClientBase:
    settings = get_settings()
    mode = settings.razorpay_mode.lower().strip()
    if mode == "fake":
        return FakeRazorpayClient()

    if credentials is None:
        raise RazorpayClientError(
            code="RAZORPAY_CREDENTIALS_MISSING",
            message="Razorpay credentials are missing for this merchant.",
        )
    if not credentials.key_id.strip() or not credentials.key_secret.strip():
        raise RazorpayClientError(
            code="RAZORPAY_CREDENTIALS_INVALID",
            message="Razorpay credentials are incomplete for this merchant.",
        )

    if mode == "test":
        key_id_looks_test = credentials.key_id.startswith("rzp_test_")
        secret_looks_test = credentials.key_secret.startswith("rzp_test_")
        if not key_id_looks_test or not secret_looks_test:
            raise RazorpayClientError(
                code="RAZORPAY_CREDENTIALS_INVALID",
                message="Test mode requires valid Razorpay test credentials.",
            )
        return RealRazorpayClient(credentials)

    if mode == "live":
        if credentials.key_id.startswith("rzp_test_"):
            raise RazorpayClientError(
                code="RAZORPAY_CREDENTIALS_INVALID",
                message="Live mode cannot use Razorpay test key IDs.",
            )
        return RealRazorpayClient(credentials)

    raise RazorpayClientError(
        code="RAZORPAY_MODE_INVALID",
        message=f"Unsupported RAZORPAY_MODE '{settings.razorpay_mode}'.",
    )
