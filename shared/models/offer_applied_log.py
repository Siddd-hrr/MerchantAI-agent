from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base


class OfferAppliedLog(Base):
    __tablename__ = "offer_applied_log"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True)
    offer_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("offers.id"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount_saved_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
