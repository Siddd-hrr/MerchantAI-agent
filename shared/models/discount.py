from uuid import UUID, uuid4

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base


class Discount(Base):
    __tablename__ = "discounts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    item_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    condition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    discount_type: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    combo_with_item_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
