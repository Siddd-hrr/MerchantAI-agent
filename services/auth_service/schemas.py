from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class MerchantSignupRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    display_name: str | None = None
    business_name: str | None = None  # alias accepted; maps to display_name
    trusted_issuers: list[str] | None = Field(default=None, min_length=1)
    trusted_mandate_issuers: list[str] | None = Field(default=None, min_length=1)
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None

    @model_validator(mode="after")
    def validate_issuer_presence(self) -> "MerchantSignupRequest":
        self.resolved_trusted_issuers()
        return self

    def resolved_display_name(self) -> str | None:
        return self.display_name or self.business_name

    def resolved_trusted_issuers(self) -> list[str]:
        issuers = self.trusted_mandate_issuers if self.trusted_mandate_issuers is not None else self.trusted_issuers
        if issuers is None:
            raise ValueError("at least one trusted issuer is required")
        cleaned = [issuer.strip() for issuer in issuers if issuer and issuer.strip()]
        if not cleaned:
            raise ValueError("at least one trusted issuer is required")
        return cleaned


class MerchantLoginRequest(BaseModel):
    email: str
    password: str


class MerchantProfileResponse(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    trusted_issuers: list[str]
    razorpay_key_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MerchantProfileUpdateRequest(BaseModel):
    display_name: str | None = None
    trusted_issuers: list[str] | None = Field(default=None, min_length=1)
    trusted_mandate_issuers: list[str] | None = Field(default=None, min_length=1)
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    password: str | None = Field(default=None, min_length=8)

    def resolved_trusted_issuers(self) -> list[str] | None:
        issuers = self.trusted_mandate_issuers if self.trusted_mandate_issuers is not None else self.trusted_issuers
        if issuers is None:
            return None
        cleaned = [issuer.strip() for issuer in issuers if issuer and issuer.strip()]
        if not cleaned:
            raise ValueError("at least one trusted issuer is required")
        return cleaned


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    profile: MerchantProfileResponse
