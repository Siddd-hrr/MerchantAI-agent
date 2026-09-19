from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.payment_log_service.payment_log_processor import PaymentLogProcessor
from services.payment_log_service.router import router as payment_log_router
from services.payment_log_service.webhook_consumer import WebhookConsumer
from services.reservation_service.reservation_service import ReservationService
from shared.config import get_settings
from shared.db import AsyncSessionLocal
from shared.redis_client import close_redis_client, get_redis_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    redis_client = get_redis_client()
    reservation_service = ReservationService(AsyncSessionLocal, redis_client=redis_client)
    processor = PaymentLogProcessor(
        AsyncSessionLocal,
        redis_client=redis_client,
        reservation_service=reservation_service,
    )
    consumer = WebhookConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        process_webhook=processor.process_webhook,
    )
    consumer_task = asyncio.create_task(consumer.consume_forever(), name="payment-log-webhook-consumer")

    _app.state.redis_client = redis_client
    try:
        yield
    finally:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pragma: no cover - defensive shutdown guard
            logger.exception("payment_log_consumer_shutdown_failed: %s", exc)
        await close_redis_client(redis_client)


app = FastAPI(title="Payment Log Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(payment_log_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "payment_log_service"}
