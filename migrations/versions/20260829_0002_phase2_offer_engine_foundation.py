"""Add Phase 2 offer engine foundation tables

Revision ID: 20260829_0002
Revises: 20260829_0001
Create Date: 2026-08-29 17:55:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260829_0002"
down_revision: Union[str, None] = "20260829_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "offers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offer_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("item_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("condition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("discount_type", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("combo_with_item_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("coupon_code", sa.String(length=64), nullable=True),
        sa.Column("festival_name", sa.String(length=255), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_offers_offer_type", "offers", ["offer_type"], unique=False)
    op.create_index("ix_offers_coupon_code", "offers", ["coupon_code"], unique=False)

    op.create_table(
        "cross_sell_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_item_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["source_item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cross_sell_preferences_source_item_id",
        "cross_sell_preferences",
        ["source_item_id"],
        unique=False,
    )

    op.create_table(
        "offer_applied_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("amount_saved_paise", sa.Integer(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_offer_applied_log_order_id", "offer_applied_log", ["order_id"], unique=False)
    op.create_index("ix_offer_applied_log_offer_id", "offer_applied_log", ["offer_id"], unique=False)

    op.create_table(
        "personal_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consumer_agent_id", sa.String(length=255), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_memory_consumer_agent_id", "personal_memory", ["consumer_agent_id"], unique=False)

    op.create_table(
        "procedural_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("playbook_name", sa.String(length=255), nullable=False),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_procedural_memory_playbook_name", "procedural_memory", ["playbook_name"], unique=False)

    op.create_table(
        "skill_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("example_input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("example_output", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("success", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skill_memory_tool_name", "skill_memory", ["tool_name"], unique=False)

    op.create_table(
        "reserved_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reserved_qty", sa.Integer(), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reserved_items_invoice_id", "reserved_items", ["invoice_id"], unique=False)
    op.create_index("ix_reserved_items_item_id", "reserved_items", ["item_id"], unique=False)
    op.create_index("ix_reserved_items_status", "reserved_items", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_reserved_items_status", table_name="reserved_items")
    op.drop_index("ix_reserved_items_item_id", table_name="reserved_items")
    op.drop_index("ix_reserved_items_invoice_id", table_name="reserved_items")
    op.drop_table("reserved_items")

    op.drop_index("ix_skill_memory_tool_name", table_name="skill_memory")
    op.drop_table("skill_memory")

    op.drop_index("ix_procedural_memory_playbook_name", table_name="procedural_memory")
    op.drop_table("procedural_memory")

    op.drop_index("ix_personal_memory_consumer_agent_id", table_name="personal_memory")
    op.drop_table("personal_memory")

    op.drop_index("ix_offer_applied_log_offer_id", table_name="offer_applied_log")
    op.drop_index("ix_offer_applied_log_order_id", table_name="offer_applied_log")
    op.drop_table("offer_applied_log")

    op.drop_index(
        "ix_cross_sell_preferences_source_item_id",
        table_name="cross_sell_preferences",
    )
    op.drop_table("cross_sell_preferences")

    op.drop_index("ix_offers_coupon_code", table_name="offers")
    op.drop_index("ix_offers_offer_type", table_name="offers")
    op.drop_table("offers")
