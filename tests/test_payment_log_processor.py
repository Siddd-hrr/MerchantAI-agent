from __future__ import annotations

import json

import pytest

from services.payment_log_service.payment_log_processor import PaymentLogProcessor


class FakeSession:
    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class FakeSessionFactory:
    def __call__(self) -> FakeSession:
        return FakeSession()


class FakeRedis:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    async def get(self, key: str) -> str | None:
        return self._values.get(key)


class FakeReservationService:
    def __init__(self) -> None:
        self.mark_paid_calls: list[str] = []

    async def mark_reserved_paid(self, invoice_id: str) -> int:
        self.mark_paid_calls.append(invoice_id)
        return 1


def _payment_event(event: str) -> dict:
    return {
        "event": event,
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_abc",
                    "order_id": "order_abc",
                    "notes": {
                        "invoice_id": "inv_1",
                        "session_id": "session_1",
                        "merchant_id": "merchant_1",
                    },
                }
            }
        },
    }


@pytest.mark.asyncio
async def test_payment_log_processor_success_marks_paid_and_writes_audit() -> None:
    redis = FakeRedis({"invoice:inv_1": json.dumps({"order_id": "inv_1", "session_id": "session_1"})})
    reservation_service = FakeReservationService()
    processor = PaymentLogProcessor(
        FakeSessionFactory(),  # type: ignore[arg-type]
        redis_client=redis,  # type: ignore[arg-type]
        reservation_service=reservation_service,  # type: ignore[arg-type]
    )

    audits: list[dict] = []

    async def capture_audit(**kwargs):  # noqa: ANN003
        audits.append(kwargs)

    async def no_reconstruct(_invoice_id: str | None) -> dict | None:
        return None

    processor._write_invoice_audit = capture_audit  # type: ignore[method-assign]
    processor._reconstruct_invoice_from_order = no_reconstruct  # type: ignore[method-assign]

    await processor.process_webhook(webhook_payload=_payment_event("payment.captured"))

    assert reservation_service.mark_paid_calls == ["inv_1"]
    assert len(audits) == 1
    assert audits[0]["payment_status"] == "SUCCESS"
    assert audits[0]["invoice_id"] == "inv_1"
    assert audits[0]["merchant_id"] == "merchant_1"


@pytest.mark.asyncio
async def test_payment_log_processor_failure_writes_audit_only() -> None:
    redis = FakeRedis({})
    reservation_service = FakeReservationService()
    processor = PaymentLogProcessor(
        FakeSessionFactory(),  # type: ignore[arg-type]
        redis_client=redis,  # type: ignore[arg-type]
        reservation_service=reservation_service,  # type: ignore[arg-type]
    )

    audits: list[dict] = []

    async def capture_audit(**kwargs):  # noqa: ANN003
        audits.append(kwargs)

    async def reconstruct_invoice(_invoice_id: str | None) -> dict | None:
        return {"order_id": "inv_1", "session_id": "session_1"}

    processor._write_invoice_audit = capture_audit  # type: ignore[method-assign]
    processor._reconstruct_invoice_from_order = reconstruct_invoice  # type: ignore[method-assign]

    await processor.process_webhook(webhook_payload=_payment_event("payment.failed"))

    assert reservation_service.mark_paid_calls == []
    assert len(audits) == 1
    assert audits[0]["payment_status"] == "FAILED"
    assert audits[0]["invoice_id"] == "inv_1"
