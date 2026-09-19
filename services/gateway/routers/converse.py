from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from uuid import uuid4

import httpx
from fastapi import APIRouter
from pydantic import ValidationError

from shared.config import get_settings
from shared.schemas.conversation import ConverseRequest, ConverseResponse

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

_rate_limit_buckets: dict[str, deque[float]] = defaultdict(deque)


def _is_rate_limited(consumer_agent_id: str, limit: int) -> bool:
    now = time.time()
    window_start = now - 60
    bucket = _rate_limit_buckets[consumer_agent_id]
    while bucket and bucket[0] < window_start:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


@router.post("/v1/converse", response_model=ConverseResponse)
async def converse(payload: ConverseRequest) -> ConverseResponse:
    session_id = payload.session_id or str(uuid4())
    logger.info(
        "gateway_converse_request consumer_agent_id=%s session_id=%s",
        payload.consumer_agent_id,
        session_id,
    )

    if _is_rate_limited(payload.consumer_agent_id, settings.rate_limit_per_minute):
        return ConverseResponse(
            session_id=session_id,
            status="FAILED",
            reply="Rate limit exceeded.",
            missing_fields=[],
            catalog_suggestions=[],
            invoice=None,
            error={"code": "RATE_LIMITED", "message": "Rate limit exceeded. Try again in a minute."},
        )

    forward_payload = {
        "consumer_agent_id": payload.consumer_agent_id,
        "session_id": session_id,
        "message": payload.message,
        "human_sign_mandate": payload.human_sign_mandate,
    }
    if payload.merchant_id:
        forward_payload["merchant_id"] = payload.merchant_id
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{settings.worker_url}/v1/worker/converse", json=forward_payload)
            response.raise_for_status()
        return ConverseResponse.model_validate(response.json())
    except httpx.HTTPError as exc:
        return ConverseResponse(
            session_id=session_id,
            status="FAILED",
            reply="Unable to process this turn.",
            missing_fields=[],
            catalog_suggestions=[],
            invoice=None,
            error={"code": "WORKER_UNAVAILABLE", "message": str(exc)},
        )
    except ValidationError as exc:
        return ConverseResponse(
            session_id=session_id,
            status="FAILED",
            reply="Unable to process this turn.",
            missing_fields=[],
            catalog_suggestions=[],
            invoice=None,
            error={"code": "WORKER_RESPONSE_INVALID", "message": str(exc)},
        )
