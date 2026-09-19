from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from aiokafka import AIOKafkaProducer
from fastapi import FastAPI
from pydantic import ValidationError

from services.async_worker.forwarder import forward_to_agent
from services.async_worker.mandate_verifier import MANDATE_INVALID_ERROR, MandateVerificationError, verify_mandate
from services.async_worker.webhook_router import router as webhook_router
from shared.config import get_settings
from shared.schemas.conversation import ConverseRequest, ConverseResponse


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks="all",
    )
    await producer.start()
    _app.state.kafka_producer = producer
    try:
        yield
    finally:
        await producer.stop()


app = FastAPI(title="Merchant Async Worker Service", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "async_worker"}


@app.post("/v1/worker/converse", response_model=ConverseResponse)
async def worker_converse(payload: ConverseRequest) -> ConverseResponse:
    session_id = payload.session_id or str(uuid4())
    try:
        await verify_mandate(
            session_id=session_id,
            consumer_agent_id=payload.consumer_agent_id,
            human_sign_mandate=payload.human_sign_mandate,
            merchant_id=payload.merchant_id,
        )
    except MandateVerificationError:
        return ConverseResponse(
            session_id=session_id,
            status="FAILED",
            reply=MANDATE_INVALID_ERROR["error"]["message"],
            missing_fields=[],
            catalog_suggestions=[],
            invoice=None,
            error=MANDATE_INVALID_ERROR["error"],
        )

    try:
        return await forward_to_agent(
            consumer_agent_id=payload.consumer_agent_id,
            session_id=session_id,
            message=payload.message,
            merchant_id=payload.merchant_id,
        )
    except httpx.HTTPError as exc:
        return ConverseResponse(
            session_id=session_id,
            status="FAILED",
            reply="Unable to process this turn.",
            missing_fields=[],
            catalog_suggestions=[],
            invoice=None,
            error={"code": "AGENT_UNAVAILABLE", "message": str(exc)},
        )
    except ValidationError as exc:
        return ConverseResponse(
            session_id=session_id,
            status="FAILED",
            reply="Unable to process this turn.",
            missing_fields=[],
            catalog_suggestions=[],
            invoice=None,
            error={"code": "AGENT_RESPONSE_INVALID", "message": str(exc)},
        )
