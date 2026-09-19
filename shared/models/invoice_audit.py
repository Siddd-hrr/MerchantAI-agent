from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base


class InvoiceAudit(Base):
    __tablename__ = "invoice_audit"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payment_status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invoice_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    webhook_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    langsmith_trace_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
