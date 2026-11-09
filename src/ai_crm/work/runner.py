"""In-process worker. The pass over tenants lives here; the pieces are in work/tick.

The kill-switch reader, circuit breaker, job creator and discovery query are looked up in this
module on every call and handed to the helpers, so tests (and operators) can replace them here.
"""

import asyncio
import logging
import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..agents import expire_overdue_runs
from ..config import settings
from ..flags import disabled_flags
from ..models import Organization, utc_now
from ..observability.service import run_proactive_checks
from ..permissions import Permission
from .breaker import CircuitBreaker
from .jobs import create_job, reconcile_expired_jobs
from .tick.context import ACTOR_ID, CONTROL, WORKER_ID, make_context  # noqa: F401
from .tick.discovery import discover_tenants
from .tick.job_run import run_one
from .tick.loop import run_loop
from .tick.rotation import rotate
from .tick.syncs import schedule_syncs

logger = logging.getLogger(__name__)

# While any provider's breaker is open, connector jobs stay queued: the claim cannot filter by
# provider, so with several providers one outage pauses all connector jobs until it cools down.
connector_breaker = CircuitBreaker(
    settings.connector_breaker_failures, settings.connector_breaker_cooldown_seconds
)
_last_start: str | None = None


async def _run_one(factory: async_sessionmaker[AsyncSession], tenant_id: str) -> bool:
    """Claim and execute one job for a tenant; return False when nothing was ready."""
    return await run_one(
        factory, tenant_id, breaker=connector_breaker, disabled_flags=disabled_flags
    )


async def enqueue_scheduled_syncs(
    factory: async_sessionmaker[AsyncSession], tenant_id: str, now: datetime
) -> int:
    """Enqueue one incremental sync per healthy connection for the current interval bucket."""
    return await schedule_syncs(factory, tenant_id, now, create_job=create_job)


async def tenants_with_work(factory: async_sessionmaker[AsyncSession], now: datetime) -> set[str]:
    """Tenants the per-tenant pass would act on this tick (see work/tick/discovery.py)."""
    return await discover_tenants(factory, now, breaker=connector_breaker)


async def _visit_tenant(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: str,
    *,
    run_proactive: bool,
    schedule_syncs: bool,
    failures: list[str] | None,
) -> int:
    """One tenant's pass: reconcile, optionally schedule syncs, run up to a batch of jobs within
    the time budget, sweep overdue agent runs, optionally run proactive checks. A failure is
    logged and recorded, never raised, and jobs already handled still count."""
    handled = 0
    try:
        async with factory() as session:
            await reconcile_expired_jobs(session, make_context(tenant_id, CONTROL))
        if schedule_syncs:
            await enqueue_scheduled_syncs(factory, tenant_id, utc_now())
        started = time.monotonic()
        for _ in range(settings.worker_batch_size):
            if not await _run_one(factory, tenant_id):
                break
            handled += 1
            if time.monotonic() - started >= settings.worker_tenant_time_budget_seconds:
                logger.debug("tenant %s used its time budget this tick", tenant_id)
                break
        async with factory() as session:
            await expire_overdue_runs(session, make_context(tenant_id, frozenset()))
        if run_proactive:
            async with factory() as session:
                await run_proactive_checks(
                    session,
                    make_context(tenant_id, frozenset({Permission.OBSERVABILITY_MANAGE})),
                )
    except Exception:
        logger.exception("worker tick failed for tenant %s", tenant_id)
        if failures is not None:
            failures.append(tenant_id)
    return handled


async def run_tick(
    factory: async_sessionmaker[AsyncSession],
    *,
    run_proactive: bool = False,
    schedule_syncs: bool = False,
    failures: list[str] | None = None,
    start_offset: int | None = None,
) -> int:
    """Process ready jobs once; return the number of jobs handled.

    Only tenants with work are visited, except on ticks that run proactive checks or schedule
    syncs (interval-driven), which visit every tenant. The visit order rotates every tick and each
    tenant has a time budget, so no tenant is always served last and a slow tenant cannot hold
    the pass for the others."""
    global _last_start
    if run_proactive or schedule_syncs:
        async with factory() as session:
            tenant_ids = sorted(await session.scalars(select(Organization.id)))
    else:
        tenant_ids = sorted(await tenants_with_work(factory, utc_now()))
    ordered, _last_start = rotate(tenant_ids, start_offset, _last_start)
    handled = 0
    for tenant_id in ordered:
        handled += await _visit_tenant(
            factory,
            tenant_id,
            run_proactive=run_proactive,
            schedule_syncs=schedule_syncs,
            failures=failures,
        )
    return handled


async def run_forever(
    factory: async_sessionmaker[AsyncSession], stop_event: asyncio.Event
) -> None:
    await run_loop(factory, stop_event, run_tick)
