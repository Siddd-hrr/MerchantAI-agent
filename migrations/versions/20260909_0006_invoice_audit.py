"""Add invoice_audit table for webhook processing.

Revision ID: 20260909_0006
Revises: 20260902_0005
Create Date: 2026-09-09
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260909_0006"
down_revision: str | None = "20260902_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invoice_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=True),
        sa.Column("merchant_id", sa.String(length=255), nullable=True),
        sa.Column("payment_status", sa.String(length=64), nullable=False),
        sa.Column("razorpay_payment_id", sa.String(length=255), nullable=True),
        sa.Column("razorpay_order_id", sa.String(length=255), nullable=True),
        sa.Column(
            "invoice_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "webhook_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("langsmith_trace_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoice_audit_invoice_id", "invoice_audit", ["invoice_id"], unique=False)
    op.create_index("ix_invoice_audit_session_id", "invoice_audit", ["session_id"], unique=False)
    op.create_index("ix_invoice_audit_merchant_id", "invoice_audit", ["merchant_id"], unique=False)
    op.create_index("ix_invoice_audit_payment_status", "invoice_audit", ["payment_status"], unique=False)
    op.create_index(
        "ix_invoice_audit_merchant_created",
        "invoice_audit",
        ["merchant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_invoice_audit_invoice_payment",
        "invoice_audit",
        ["invoice_id", "razorpay_payment_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_invoice_audit_invoice_payment", table_name="invoice_audit")
    op.drop_index("ix_invoice_audit_merchant_created", table_name="invoice_audit")
    op.drop_index("ix_invoice_audit_payment_status", table_name="invoice_audit")
    op.drop_index("ix_invoice_audit_merchant_id", table_name="invoice_audit")
    op.drop_index("ix_invoice_audit_session_id", table_name="invoice_audit")
    op.drop_index("ix_invoice_audit_invoice_id", table_name="invoice_audit")
    op.drop_table("invoice_audit")
