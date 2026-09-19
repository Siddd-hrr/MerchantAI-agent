from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_service.jwt_tokens import decode_token
from services.payment_log_service.ingress_forwarder import forward_to_worker
from services.payment_log_service.schemas import InvoiceAuditListResponse, InvoiceAuditResponse
from shared.config import get_settings
from shared.db import AsyncSessionLocal
from shared.models.invoice_audit import InvoiceAudit

router = APIRouter(tags=["payment-log"])
bearer_scheme = HTTPBearer(auto_error=False)


async def get_db_dependency() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_merchant_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    try:
        payload = decode_token(credentials.credentials)
        merchant_id = str(UUID(str(payload["sub"])))
    except (ValueError, KeyError, jwt.PyJWTError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token.") from None
    return merchant_id


@router.post("/webhook/razorpay")
async def ingress_razorpay_webhook(request: Request) -> Response:
    settings = get_settings()
    raw_body = await request.body()
    headers = {key: value for key, value in request.headers.items()}
    result = await forward_to_worker(
        worker_url=settings.worker_url,
        raw_body=raw_body,
        headers=headers,
    )
    return Response(
        content=result.body,
        status_code=result.status_code,
        media_type=result.media_type,
    )


@router.get("/invoice-audit/", response_model=InvoiceAuditListResponse)
async def list_invoice_audit(
    limit: int = Query(default=100, ge=1, le=500),
    merchant_id: str = Depends(get_current_merchant_id),
    db_session: AsyncSession = Depends(get_db_dependency),
) -> InvoiceAuditListResponse:
    result = await db_session.execute(
        select(InvoiceAudit)
        .where(InvoiceAudit.merchant_id == merchant_id)
        .order_by(InvoiceAudit.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return InvoiceAuditListResponse(items=[InvoiceAuditResponse.model_validate(row) for row in rows])


@router.get("/invoice-audit/{invoice_id}", response_model=InvoiceAuditListResponse)
async def get_invoice_audit(
    invoice_id: str,
    merchant_id: str = Depends(get_current_merchant_id),
    db_session: AsyncSession = Depends(get_db_dependency),
) -> InvoiceAuditListResponse:
    result = await db_session.execute(
        select(InvoiceAudit)
        .where(InvoiceAudit.invoice_id == invoice_id, InvoiceAudit.merchant_id == merchant_id)
        .order_by(InvoiceAudit.created_at.desc())
    )
    rows = result.scalars().all()
    return InvoiceAuditListResponse(items=[InvoiceAuditResponse.model_validate(row) for row in rows])
