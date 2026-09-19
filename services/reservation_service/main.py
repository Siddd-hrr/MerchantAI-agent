from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.reservation_service.reservation_service import ReservationService
from services.reservation_service.rollback_scheduler import RollbackScheduler
from services.reservation_service.router import build_router
from shared.db import AsyncSessionLocal

reservation_service = ReservationService(AsyncSessionLocal)
rollback_scheduler = RollbackScheduler(reservation_service)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    rollback_scheduler.start()
    try:
        yield
    finally:
        await rollback_scheduler.stop()


app = FastAPI(title="Reservation Service", lifespan=lifespan)
app.include_router(build_router(reservation_service))


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "reservation_service"}
