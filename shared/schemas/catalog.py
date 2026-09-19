from pydantic import BaseModel, Field


class CatalogSuggestion(BaseModel):
    item_id: str
    name: str
    brand: str
    price_paise: int = Field(ge=0)
    available_qty: int = Field(ge=0)
    weight_per_unit: str
    expiry_date: str
