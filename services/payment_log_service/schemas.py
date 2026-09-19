from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class InvoiceAuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: str
    session_id: str | None
    merchant_id: str | None
    payment_status: str
    razorpay_payment_id: str | None
    razorpay_order_id: str | None
    invoice_payload: dict
    webhook_payload: dict
    langsmith_trace_url: str | None
    created_at: datetime


class InvoiceAuditListResponse(BaseModel):
    items: list[InvoiceAuditResponse]
