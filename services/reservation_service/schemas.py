from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from shared.schemas.invoice import Invoice


class ReservationSubmitLineItem(BaseModel):
    item_id: str
    qty: int = Field(ge=1)


class ReservationUnavailableItem(BaseModel):
    item_id: str
    requested_qty: int = Field(ge=1)
    available_qty: int = Field(ge=0)


class ReservationSubmitInvoiceRequest(BaseModel):
    invoice: Invoice | None = None
    invoice_id: str | None = None
    line_items: list[ReservationSubmitLineItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_shape(self) -> "ReservationSubmitInvoiceRequest":
        if self.invoice is not None:
            return self
        if self.invoice_id and self.line_items:
            return self
        raise ValueError("payload must include either invoice or invoice_id with line_items")


class ReservationSubmitInvoiceResponse(BaseModel):
    success: bool
    invoice: Invoice | None = None
    unavailable_items: list[ReservationUnavailableItem] = Field(default_factory=list)
    reserved_at: str | None = None
    expires_at: str | None = None
