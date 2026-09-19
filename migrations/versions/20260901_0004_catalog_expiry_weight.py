"""Replace unit/category with weight_per_unit and expiry_date.

Revision ID: 20260901_0004
Revises: 20260830_0003
Create Date: 2026-09-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260901_0004"
down_revision = "20260830_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("items", sa.Column("weight_per_unit", sa.String(length=10), nullable=True))
    op.add_column("items", sa.Column("expiry_date", sa.Date(), nullable=True))

    op.execute(
        """
        UPDATE items
        SET weight_per_unit = CASE
            WHEN lower(unit) LIKE '%ml%' THEN 'ml'
            WHEN lower(unit) ~ '(^|[^a-z])l([^a-z]|$)' OR lower(unit) LIKE '%liter%' THEN 'L'
            WHEN lower(unit) LIKE '%kg%' THEN 'kg'
            WHEN lower(unit) LIKE '%g%' THEN 'g'
            ELSE 'kg'
        END
        """
    )
    op.execute("UPDATE items SET expiry_date = DATE '2099-12-31' WHERE expiry_date IS NULL")
    op.execute(
        """
        UPDATE items AS keeper
        SET quantity_available = keeper.quantity_available + dup.total_qty
        FROM (
            SELECT lower(name) AS lname,
                   lower(brand) AS lbrand,
                   expiry_date,
                   lower(weight_per_unit) AS lweight,
                   MIN(id::text)::uuid AS keeper_id,
                   SUM(quantity_available) AS total_qty
            FROM items
            GROUP BY lower(name), lower(brand), expiry_date, lower(weight_per_unit)
            HAVING COUNT(*) > 1
        ) AS dup
        WHERE lower(keeper.name) = dup.lname
          AND lower(keeper.brand) = dup.lbrand
          AND keeper.expiry_date = dup.expiry_date
          AND lower(keeper.weight_per_unit) = dup.lweight
          AND keeper.id = dup.keeper_id
        """
    )
    op.execute(
        """
        DELETE FROM items
        WHERE id IN (
            SELECT id
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY lower(name), lower(brand), expiry_date, lower(weight_per_unit)
                           ORDER BY updated_at DESC, id
                       ) AS rn
                FROM items
            ) ranked
            WHERE rn > 1
        )
        """
    )

    op.alter_column("items", "weight_per_unit", nullable=False)
    op.alter_column("items", "expiry_date", nullable=False)
    op.drop_column("items", "unit")
    op.drop_column("items", "category")

    op.create_index(
        "uq_items_identity",
        "items",
        [sa.text("lower(name)"), sa.text("lower(brand)"), "expiry_date", sa.text("lower(weight_per_unit)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_items_identity", table_name="items")
    op.add_column("items", sa.Column("category", sa.String(length=255), nullable=True))
    op.add_column("items", sa.Column("unit", sa.String(length=50), nullable=True))
    op.execute("UPDATE items SET category = 'General', unit = weight_per_unit")
    op.alter_column("items", "category", nullable=False)
    op.alter_column("items", "unit", nullable=False)
    op.drop_column("items", "expiry_date")
    op.drop_column("items", "weight_per_unit")
