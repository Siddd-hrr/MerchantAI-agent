from pydantic import BaseModel, Field


class MandateClaims(BaseModel):
    issuer: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    issued_at: int
    signature: str = Field(min_length=1)
