"""Drop reserved_items.invoice_id FK so holds can exist before order row.

Revision ID: 20260830_0003
Revises: 20260829_0002
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op

revision = "20260830_0003"
down_revision = "20260829_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reservation is created in finalize_order before the invoice/order row exists.
    # invoice_id is a correlation id that later matches orders.id.
    op.drop_constraint("reserved_items_invoice_id_fkey", "reserved_items", type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key(
        "reserved_items_invoice_id_fkey",
        "reserved_items",
        "orders",
        ["invoice_id"],
        ["id"],
    )
