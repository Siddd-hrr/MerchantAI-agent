from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(slots=True)
class ForwardResult:
    status_code: int
    body: str
    media_type: str


def _build_forward_headers(headers: dict[str, str]) -> dict[str, str]:
    blocked = {"host", "content-length", "connection"}
    return {key: value for key, value in headers.items() if key.lower() not in blocked}


async def forward_to_worker(*, worker_url: str, raw_body: bytes, headers: dict[str, str]) -> ForwardResult:
    endpoint = f"{worker_url.rstrip('/')}/internal/razorpay-webhook/verify-enqueue"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            endpoint,
            content=raw_body,
            headers=_build_forward_headers(headers),
        )
    content_type = response.headers.get("content-type", "text/plain")
    media_type = content_type.split(";")[0].strip() or "text/plain"
    return ForwardResult(
        status_code=response.status_code,
        body=response.text,
        media_type=media_type,
    )
