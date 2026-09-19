from __future__ import annotations

import httpx

from shared.config import get_settings
from shared.schemas.conversation import ConverseResponse


async def forward_to_agent(
    *,
    consumer_agent_id: str,
    session_id: str,
    message: str,
    merchant_id: str | None = None,
) -> ConverseResponse:
    settings = get_settings()
    payload = {
        "consumer_agent_id": consumer_agent_id,
        "session_id": session_id,
        "message": message,
        "mandate_verified": True,
    }
    if merchant_id:
        payload["merchant_id"] = merchant_id
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(f"{settings.agent_url}/v1/agent/turn", json=payload)
        response.raise_for_status()
        return ConverseResponse.model_validate(response.json())
