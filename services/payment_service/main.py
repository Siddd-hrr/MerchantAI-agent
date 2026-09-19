from fastapi import FastAPI

from services.payment_service.credential_store import MerchantCredentialStore
from services.payment_service.router import build_router
from shared.db import AsyncSessionLocal
from shared.redis_client import get_redis_client

redis_client = get_redis_client()
credential_store = MerchantCredentialStore(AsyncSessionLocal, redis_client=redis_client)

app = FastAPI(title="Payment Service")
app.include_router(build_router(credential_store, redis_client))


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "payment_service"}
