import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...config import settings
from ...models import utc_now

logger = logging.getLogger("ai_crm.work.runner")

TickRunner = Callable[..., Awaitable[int]]


def elapsed(last: datetime | None, now: datetime, seconds: float) -> bool:
    return last is None or (now - last).total_seconds() >= seconds


async def run_loop(
    factory: async_sessionmaker[AsyncSession], stop_event: asyncio.Event, run_tick: TickRunner
) -> None:
    last_proactive: datetime | None = None
    last_sync_schedule: datetime | None = None
    while not stop_event.is_set():
        now = utc_now()
        due = elapsed(last_proactive, now, settings.proactive_check_interval_seconds)
        sync_due = elapsed(last_sync_schedule, now, settings.integration_sync_interval_seconds)
        failures: list[str] = []
        try:
            await run_tick(
                factory, run_proactive=due, schedule_syncs=sync_due, failures=failures
            )
            # A failed tenant pass is retried on the next tick instead of waiting a full interval.
            if due and not failures:
                last_proactive = now
            if sync_due and not failures:
                last_sync_schedule = now
        except Exception:
            logger.exception("worker tick failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.worker_poll_seconds)
        except TimeoutError:
            pass
