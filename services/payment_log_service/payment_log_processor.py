from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote_plus
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.reservation_service.reservation_service import ReservationService
from shared.config import get_settings
from shared.models.invoice_audit import InvoiceAudit
from shared.models.order import Order


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _extract_notes(webhook_payload: dict[str, Any]) -> dict[str, Any]:
    payload = _safe_dict(webhook_payload.get("payload"))
    payment_entity = _safe_dict(_safe_dict(payload.get("payment")).get("entity"))
    payment_link_entity = _safe_dict(_safe_dict(payload.get("payment_link")).get("entity"))
    candidates: list[dict[str, Any]] = [
        _safe_dict(payment_entity.get("notes")),
        _safe_dict(payment_link_entity.get("notes")),
        _safe_dict(payload.get("notes")),
        _safe_dict(webhook_payload.get("notes")),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return {}


def _is_payment_success(webhook_payload: dict[str, Any]) -> bool:
    event = str(webhook_payload.get("event", "")).strip().lower()
    if event in {"payment.captured", "payment_link.paid"}:
        return True

    payload = _safe_dict(webhook_payload.get("payload"))
    payment_status = str(_safe_dict(_safe_dict(payload.get("payment")).get("entity")).get("status", "")).lower()
    payment_link_status = str(_safe_dict(_safe_dict(payload.get("payment_link")).get("entity")).get("status", "")).lower()
    return payment_status == "captured" or payment_link_status == "paid"


def _extract_payment_identifiers(webhook_payload: dict[str, Any]) -> tuple[str | None, str | None]:
    payload = _safe_dict(webhook_payload.get("payload"))
    payment_entity = _safe_dict(_safe_dict(payload.get("payment")).get("entity"))
    payment_link_entity = _safe_dict(_safe_dict(payload.get("payment_link")).get("entity"))
    razorpay_payment_id = payment_entity.get("id") or webhook_payload.get("payment_id")
    razorpay_order_id = payment_entity.get("order_id") or payment_link_entity.get("reference_id")
    return (
        str(razorpay_payment_id) if razorpay_payment_id else None,
        str(razorpay_order_id) if razorpay_order_id else None,
    )


def _build_langsmith_trace_url(session_id: str | None) -> str | None:
    if not session_id:
        return None
    settings = get_settings()
    project = quote_plus(settings.langchain_project)
    query = quote_plus(f'session_id:"{session_id}"')
    return f"https://smith.langchain.com/?project={project}&query={query}"


class PaymentLogProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        redis_client: Redis,
        reservation_service: ReservationService,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._reservation_service = reservation_service

    async def _load_invoice_from_redis(self, invoice_id: str | None) -> dict[str, Any] | None:
        if not invoice_id:
            return None
        raw = await self._redis.get(f"invoice:{invoice_id}")
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _reconstruct_invoice_from_order(self, invoice_id: str | None) -> dict[str, Any] | None:
        if not invoice_id:
            return None
        try:
            normalized_invoice_id = UUID(str(invoice_id))
        except ValueError:
            return None

        async with self._session_factory() as db_session:
            order = (
                await db_session.execute(select(Order).where(Order.id == normalized_invoice_id))
            ).scalar_one_or_none()
        if order is None:
            return None

        return {
            "order_id": str(order.id),
            "session_id": order.session_id,
            "customer_name": order.customer_name,
            "address": order.address,
            "phone_number": order.phone_number,
            "line_items": order.line_items or [],
            "total_paise": order.total_paise,
            "status": order.status,
        }

    async def _write_invoice_audit(
        self,
        *,
        invoice_id: str,
        session_id: str | None,
        merchant_id: str | None,
        payment_status: str,
        razorpay_payment_id: str | None,
        razorpay_order_id: str | None,
        invoice_payload: dict[str, Any],
        webhook_payload: dict[str, Any],
    ) -> None:
        async with self._session_factory() as db_session:
            try:
                async with db_session.begin():
                    db_session.add(
                        InvoiceAudit(
                            invoice_id=invoice_id,
                            session_id=session_id,
                            merchant_id=merchant_id,
                            payment_status=payment_status,
                            razorpay_payment_id=razorpay_payment_id,
                            razorpay_order_id=razorpay_order_id,
                            invoice_payload=invoice_payload,
                            webhook_payload=webhook_payload,
                            langsmith_trace_url=_build_langsmith_trace_url(session_id),
                        )
                    )
            except IntegrityError:
                # Duplicate (invoice_id, razorpay_payment_id) from Razorpay retries — treat as success.
                return

    async def process_webhook(
        self,
        *,
        webhook_payload: dict[str, Any],
        received_headers: dict[str, Any] | None = None,
    ) -> None:
        _ = received_headers
        notes = _extract_notes(webhook_payload)
        invoice_id = str(notes.get("invoice_id") or "").strip() or None
        session_id = str(notes.get("session_id") or "").strip() or None
        merchant_id = str(notes.get("merchant_id") or "").strip() or None

        invoice_payload = await self._load_invoice_from_redis(invoice_id)
        if invoice_payload is None:
            invoice_payload = await self._reconstruct_invoice_from_order(invoice_id)
        if invoice_payload is None:
            invoice_payload = {}

        if not session_id:
            candidate_session_id = invoice_payload.get("session_id")
            if isinstance(candidate_session_id, str) and candidate_session_id.strip():
                session_id = candidate_session_id
        if not merchant_id:
            candidate_merchant_id = invoice_payload.get("merchant_id")
            if isinstance(candidate_merchant_id, str) and candidate_merchant_id.strip():
                merchant_id = candidate_merchant_id

        is_success = _is_payment_success(webhook_payload)
        payment_status = "SUCCESS" if is_success else "FAILED"
        razorpay_payment_id, razorpay_order_id = _extract_payment_identifiers(webhook_payload)
        audit_invoice_id = invoice_id or str(razorpay_order_id or razorpay_payment_id or "unknown")

        await self._write_invoice_audit(
            invoice_id=audit_invoice_id,
            session_id=session_id,
            merchant_id=merchant_id,
            payment_status=payment_status,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_order_id=razorpay_order_id,
            invoice_payload=invoice_payload,
            webhook_payload=webhook_payload,
        )

        if is_success and invoice_id:
            try:
                await self._reservation_service.mark_reserved_paid(invoice_id)
            except ValueError:
                # Invalid invoice IDs should not fail audit persistence.
                return
