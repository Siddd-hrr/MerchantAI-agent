from __future__ import annotations

import json
from datetime import datetime, timezone

from aiokafka import AIOKafkaProducer
from fastapi import APIRouter, HTTPException, Request, status

from services.async_worker.webhook_verifier import verify_razorpay_signature
from shared.config import get_settings

WEBHOOK_TOPIC = "webhook-queue"

router = APIRouter(tags=["webhooks"])


@router.post("/internal/razorpay-webhook/verify-enqueue")
async def verify_and_enqueue_razorpay_webhook(request: Request) -> dict[str, str]:
    settings = get_settings()
    producer: AIOKafkaProducer | None = getattr(request.app.state, "kafka_producer", None)
    if producer is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Kafka producer is unavailable.",
        )

    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    is_valid = verify_razorpay_signature(
        body=raw_body,
        signature=signature,
        secret=settings.razorpay_webhook_secret,
    )
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Razorpay signature.")

    message = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "headers": {key: value for key, value in request.headers.items()},
        "raw_body": raw_body.decode("utf-8", errors="replace"),
    }
    try:
        await producer.send_and_wait(
            WEBHOOK_TOPIC,
            json.dumps(message).encode("utf-8"),
        )
    except Exception as exc:  # pragma: no cover - network failures are environment dependent
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist webhook message: {exc}",
        ) from exc

    return {"status": "enqueued"}
