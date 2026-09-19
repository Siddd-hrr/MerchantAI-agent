from typing import Literal

from pydantic import BaseModel, Field

from shared.schemas.catalog import CatalogSuggestion
from shared.schemas.invoice import Invoice

ConversationStatus = Literal["AWAITING_FIELDS", "AWAITING_CONFIRMATION", "VALIDATED", "INVOICED", "FAILED"]


class ConverseRequest(BaseModel):
    consumer_agent_id: str = Field(min_length=1)
    merchant_id: str | None = None
    session_id: str | None = None
    message: str = Field(min_length=1)
    human_sign_mandate: str = Field(min_length=1)


class ConverseError(BaseModel):
    code: str
    message: str


class ConverseResponse(BaseModel):
    session_id: str
    status: ConversationStatus
    reply: str
    missing_fields: list[str] = Field(default_factory=list)
    catalog_suggestions: list[CatalogSuggestion] = Field(default_factory=list)
    invoice: Invoice | None = None
    error: ConverseError | None = None
