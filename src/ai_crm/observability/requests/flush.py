import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...config import settings
from ...models import RequestMetricBucket, utc_now
from .recorder import LATENCY_BOUNDS_MS, PROCESS_ID, RequestRecorder, request_recorder

__all__ = ["flush_request_metrics", "request_metrics_loop"]

logger = logging.getLogger(__name__)
PRUNE_EVERY_FLUSHES = 120
LATENCY_COLUMNS = [f"le_{bound}" for bound in LATENCY_BOUNDS_MS] + ["le_inf"]


async def flush_request_metrics(
    factory: async_sessionmaker[AsyncSession], recorder: RequestRecorder = request_recorder
) -> int:
    """Write the accumulated buckets as new rows; return how many. On failure the counts are put
    back and retried on the next flush."""
    if recorder.dropped:
        logger.warning("dropped %d request metric samples (key cap reached)", recorder.dropped)
        recorder.dropped = 0
    drained = recorder.drain()
    if not drained:
        return 0
    rows = [
        RequestMetricBucket(
            tenant_id=tenant_id,
            bucket_start=minute,
            route=route,
            method=method,
            status_class=status_class,
            process_id=PROCESS_ID,
            count=bucket.count,
            latency_sum_ms=bucket.latency_sum_ms,
            **dict(zip(LATENCY_COLUMNS, bucket.latency_counts)),
        )
        for (minute, tenant_id, route, method, status_class), bucket in drained.items()
    ]
    try:
        async with factory() as session:
            session.add_all(rows)
            await session.commit()
    except Exception:
        logger.exception("could not flush request metrics; will retry")
        recorder.restore(drained)
        return 0
    return len(rows)


async def _prune_platform_rows(factory: async_sessionmaker[AsyncSession]) -> None:
    """Rows for requests outside any tenant have no tenant admin to purge them."""
    cutoff = utc_now() - timedelta(days=settings.observability_retention_days)
    async with factory() as session:
        await session.execute(
            delete(RequestMetricBucket).where(
                RequestMetricBucket.tenant_id == "", RequestMetricBucket.bucket_start < cutoff
            )
        )
        await session.commit()


async def request_metrics_loop(
    factory: async_sessionmaker[AsyncSession], stop_event: asyncio.Event
) -> None:
    flushes = 0
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.request_metrics_flush_seconds
            )
        except TimeoutError:
            pass
        await flush_request_metrics(factory)
        flushes += 1
        if flushes % PRUNE_EVERY_FLUSHES == 0:
            try:
                await _prune_platform_rows(factory)
            except Exception:
                logger.exception("could not prune platform request metrics")
    await flush_request_metrics(factory)  # shutdown can arrive before the first wait
