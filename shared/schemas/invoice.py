from pydantic import BaseModel, Field


class InvoiceLineItem(BaseModel):
    item_id: str
    name: str
    brand: str
    qty: int = Field(ge=1)
    unit_price_paise: int = Field(ge=0)
    line_total_paise: int = Field(ge=0)
    weight_per_unit: str | None = None


class AcceptedOffer(BaseModel):
    offer_id: str
    description: str
    amount_saved_paise: int = Field(ge=0)


class Invoice(BaseModel):
    order_id: str
    session_id: str
    issued_at: str
    merchant_name: str
    customer_name: str | None = None
    address: str | None = None
    phone_number: str | None = None
    line_items: list[InvoiceLineItem]
    subtotal_paise: int = Field(ge=0)
    discount_paise: int = Field(ge=0)
    taxable_paise: int = Field(ge=0)
    cgst_paise: int = Field(ge=0)
    sgst_paise: int = Field(ge=0)
    tax_paise: int = Field(ge=0)
    shipping_paise: int = Field(ge=0)
    total_paise: int = Field(ge=0)
    accepted_offers: list[AcceptedOffer] = Field(default_factory=list)
    payment_link_url: str | None = None
    payment_expires_at: str | None = None
    reservation_expires_at: str | None = None
