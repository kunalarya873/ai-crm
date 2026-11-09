from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...agents import overdue_run_condition
from ...config import settings
from ...models import AgentRun, DurableJob, TenantFeatureFlag
from ..breaker import CircuitBreaker
from ..handlers import HANDLERS
from ..jobs import expired_condition, ready_condition
from .context import CONNECTOR_JOB_TYPES, QUEUE


async def discover_tenants(
    factory: async_sessionmaker[AsyncSession], now: datetime, *, breaker: CircuitBreaker
) -> set[str]:
    """Tenants the per-tenant pass would act on this tick: claimable ready jobs, running jobs
    whose lease or timeout has passed, and agent runs past their deadline.

    Deliberately cross-tenant (the worker already lists every tenant) and index-backed, so an
    idle tick costs a couple of queries instead of several per tenant. Ready jobs the worker
    cannot claim do not make a tenant busy: types without a handler (they wait for external
    workers), and connector jobs held back by the platform kill switch, a tenant kill switch or
    an open circuit breaker. Expired leases are always discovered, whatever the queue or type,
    because reconciliation is not limited to claimable jobs."""
    claimable_types = set(HANDLERS)
    if breaker.blocked() or "connectors" in settings.disabled_capability_set:
        claimable_types -= CONNECTOR_JOB_TYPES
    ready = ready_condition(now) & (DurableJob.queue == QUEUE)
    ready = ready & DurableJob.job_type.in_(claimable_types)
    if CONNECTOR_JOB_TYPES & claimable_types:
        switched_off = exists().where(
            TenantFeatureFlag.tenant_id == DurableJob.tenant_id,
            TenantFeatureFlag.flag_key == "connectors",
            TenantFeatureFlag.enabled.is_(False),
        )
        ready = ready & ~(DurableJob.job_type.in_(CONNECTOR_JOB_TYPES) & switched_off)
    async with factory() as session:
        job_tenants = await session.scalars(
            select(DurableJob.tenant_id).where(ready | expired_condition(now)).distinct()
        )
        run_tenants = await session.scalars(
            select(AgentRun.tenant_id).where(overdue_run_condition(now)).distinct()
        )
        return set(job_tenants) | set(run_tenants)
