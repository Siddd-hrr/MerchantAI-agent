from __future__ import annotations

import asyncio
import logging

from services.reservation_service.reservation_service import ReservationService
from shared.config import get_settings

logger = logging.getLogger(__name__)


class RollbackScheduler:
    def __init__(self, service: ReservationService) -> None:
        self._service = service
        self._task: asyncio.Task[None] | None = None

    async def _run(self) -> None:
        interval_seconds = max(1, int(get_settings().reservation_scan_interval_seconds))
        while True:
            try:
                released_invoices = await self._service.rollback_expired_holds()
                if released_invoices:
                    logger.info("rolled_back_expired_invoices=%s", released_invoices)
            except Exception as exc:  # pragma: no cover - defensive scheduler guard
                logger.exception("rollback_scheduler_failed: %s", exc)
            await asyncio.sleep(interval_seconds)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="reservation-rollback-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
