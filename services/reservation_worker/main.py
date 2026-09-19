from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.reservation_worker.reservation_service import ReservationService
from shared.config import get_settings
from shared.db import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def _reservation_scan_loop(service: ReservationService) -> None:
    settings = get_settings()
    interval = max(1, int(settings.reservation_scan_interval_seconds))
    while True:
        try:
            expired = await service.release_expired_holds()
            if expired:
                logger.info("released_expired_holds=%s", expired)
        except Exception as exc:  # pragma: no cover - defensive service loop guard
            logger.exception("reservation_scan_failed: %s", exc)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    service = ReservationService(session_factory=AsyncSessionLocal)
    task = asyncio.create_task(_reservation_scan_loop(service), name="reservation-scan-loop")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Reservation Worker Service", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "reservation_worker"}
