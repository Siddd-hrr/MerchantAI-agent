from __future__ import annotations

from pydantic import AliasChoices, BaseModel, Field
from redis.asyncio import Redis
from fastapi import APIRouter

from services.payment_service.credential_store import MerchantCredentialStore
from services.payment_service.razorpay_client import (
    FakeRazorpayClient,
    RazorpayClientError,
    get_razorpay_client,
)


class CreatePaymentLinkRequest(BaseModel):
    merchant_id: str = Field(min_length=1)
    invoice_id: str = Field(min_length=1)
    amount_paise: int = Field(ge=1)
    session_id: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = Field(default=None, validation_alias=AliasChoices("customer_phone", "phone"))
    description: str | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str


class CreatePaymentLinkResponse(BaseModel):
    success: bool
    invoice_id: str
    payment_link_id: str | None = None
    payment_link_url: str | None = None
    expires_at: str | None = None
    mode: str | None = None
    error: ErrorDetail | None = None


class CancelPaymentLinkRequest(BaseModel):
    merchant_id: str = Field(min_length=1)
    invoice_id: str = Field(min_length=1)


class CancelPaymentLinkResponse(BaseModel):
    success: bool
    invoice_id: str
    cancelled: bool | None = None
    error: ErrorDetail | None = None


def build_router(credential_store: MerchantCredentialStore, redis_client: Redis) -> APIRouter:
    router = APIRouter(tags=["payment"])

    @router.post("/payment/create-link", response_model=CreatePaymentLinkResponse)
    async def create_payment_link(payload: CreatePaymentLinkRequest) -> CreatePaymentLinkResponse:
        from datetime import datetime, timedelta, timezone

        from shared.config import get_settings

        try:
            settings = get_settings()
            credentials = await credential_store.get_credentials(payload.merchant_id)
            client = get_razorpay_client(credentials)
            link = await client.create_link(
                merchant_id=payload.merchant_id,
                invoice_id=payload.invoice_id,
                session_id=payload.session_id,
                amount_paise=payload.amount_paise,
                customer_name=payload.customer_name,
                customer_phone=payload.customer_phone,
                description=payload.description,
            )
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=int(settings.payment_link_ttl_seconds))
            ).isoformat()

            await redis_client.set(f"payment_link:{payload.invoice_id}", link.payment_link_id, ex=600)
            mode = "fake" if isinstance(client, FakeRazorpayClient) else settings.razorpay_mode.lower().strip()
            return CreatePaymentLinkResponse(
                success=True,
                invoice_id=payload.invoice_id,
                payment_link_id=link.payment_link_id,
                payment_link_url=link.payment_link_url,
                expires_at=expires_at,
                mode=mode,
            )
        except RazorpayClientError as exc:
            return CreatePaymentLinkResponse(
                success=False,
                invoice_id=payload.invoice_id,
                error=ErrorDetail(code=exc.code, message=exc.message),
            )
        except Exception:
            return CreatePaymentLinkResponse(
                success=False,
                invoice_id=payload.invoice_id,
                error=ErrorDetail(code="PAYMENT_LINK_CREATE_FAILED", message="Unable to create payment link."),
            )

    @router.post("/payment/cancel-link", response_model=CancelPaymentLinkResponse)
    async def cancel_payment_link(payload: CancelPaymentLinkRequest) -> CancelPaymentLinkResponse:
        try:
            key = f"payment_link:{payload.invoice_id}"
            payment_link_id = await redis_client.get(key)
            if not payment_link_id:
                return CancelPaymentLinkResponse(success=True, invoice_id=payload.invoice_id, cancelled=False)

            credentials = await credential_store.get_credentials(payload.merchant_id)
            client = get_razorpay_client(credentials)
            if isinstance(client, FakeRazorpayClient):
                await redis_client.delete(key)
                return CancelPaymentLinkResponse(success=True, invoice_id=payload.invoice_id, cancelled=True)

            await client.cancel_link(payment_link_id=str(payment_link_id))
            await redis_client.delete(key)
            return CancelPaymentLinkResponse(success=True, invoice_id=payload.invoice_id, cancelled=True)
        except RazorpayClientError as exc:
            return CancelPaymentLinkResponse(
                success=False,
                invoice_id=payload.invoice_id,
                error=ErrorDetail(code=exc.code, message=exc.message),
            )
        except Exception:
            return CancelPaymentLinkResponse(
                success=False,
                invoice_id=payload.invoice_id,
                error=ErrorDetail(code="PAYMENT_LINK_CANCEL_FAILED", message="Unable to cancel payment link."),
            )

    return router
