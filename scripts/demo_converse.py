from __future__ import annotations

import argparse
import asyncio
import base64
import json
from datetime import datetime, timezone

import httpx


def build_mandate(*, issuer: str, subject: str, invalid: bool) -> str:
    issued_at = int(datetime.now(timezone.utc).timestamp())
    if invalid:
        issued_at -= 3600
    payload = {
        "issuer": issuer,
        "subject": subject,
        "issued_at": issued_at,
        "signature": "demo-signature",
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Send a demo converse request to gateway.")
    parser.add_argument("--gateway-url", default="http://localhost:8000", help="Gateway base URL.")
    parser.add_argument("--consumer-agent-id", default="consumer-demo-1", help="Consumer agent identifier.")
    parser.add_argument("--session-id", default=None, help="Optional session id.")
    parser.add_argument("--message", default="I want to order milk", help="Conversation message.")
    parser.add_argument("--issuer", default="issuer-a", help="Mandate issuer.")
    parser.add_argument("--subject", default="consumer-demo-1", help="Mandate subject.")
    parser.add_argument("--invalid-mandate", action="store_true", help="Send stale mandate for failure demo.")
    args = parser.parse_args()

    request_payload = {
        "consumer_agent_id": args.consumer_agent_id,
        "session_id": args.session_id,
        "message": args.message,
        "human_sign_mandate": build_mandate(
            issuer=args.issuer,
            subject=args.subject,
            invalid=args.invalid_mandate,
        ),
    }

    print("Request:")
    print(json.dumps(request_payload, indent=2))
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"{args.gateway_url}/v1/converse", json=request_payload)
    print(f"\nHTTP {response.status_code} Response:")
    print(json.dumps(response.json(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
