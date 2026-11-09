import asyncio
import logging
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..agents import expire_overdue_runs, overdue_run_condition
from ..api.deps import RequestContext
from ..config import settings
from ..domain import (
    BackpressureError,
    CapabilityDisabledError,
    ConflictError,
    DomainError,
    InvalidRequestError,
)
from ..flags import disabled_flags, is_enabled
from ..integrations import (
    TRANSIENT_PROVIDER_CODES,
    ConnectorProviderError,
    refresh_connection,
)
from ..models import (
    AgentRun,
    DurableJob,
    IntegrationConnection,
    IntegrationSyncRun,
    Organization,
    TenantFeatureFlag,
    WebhookEvent,
    utc_now,
)
from ..observability.service import run_proactive_checks
from ..permissions import Permission
from ..schemas import JobCreate, JobFailureRequest
from .breaker import CircuitBreaker
from .handlers import HANDLERS, SyncFailedError
from .jobs import (
    claim_next_job,
    complete_job,
    create_job,
    expired_condition,
    fail_job,
    heartbeat_job,
    ready_condition,
    reconcile_expired_jobs,
)

logger = logging.getLogger(__name__)

ACTOR_ID = "system:worker"
WORKER_ID = f"worker-{uuid4().hex[:12]}"
QUEUE = "default"
LEASE_GRACE_SECONDS = 30
CONNECTOR_JOB_TYPES = frozenset({"integration.sync", "integration.webhook"})

# While any provider's breaker is open, connector jobs stay queued: the claim cannot filter by
# provider, so with several providers one outage pauses all connector jobs until it cools down.
connector_breaker = CircuitBreaker(
    settings.connector_breaker_failures, settings.connector_breaker_cooldown_seconds
)
_last_start: str | None = None


async def _job_provider(session: AsyncSession, tenant_id: str, job: DurableJob) -> str:
    statement = select(IntegrationConnection.provider_key).where(
        IntegrationConnection.tenant_id == tenant_id
    )
    if job.payload.get("connection_id") is not None:
        statement = statement.where(IntegrationConnection.id == str(job.payload["connection_id"]))
    elif job.payload.get("event_id") is not None:
        statement = statement.join(
            WebhookEvent, WebhookEvent.connection_id == IntegrationConnection.id
        ).where(WebhookEvent.id == str(job.payload["event_id"]))
    else:
        return "unknown"
    return await session.scalar(statement) or "unknown"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _context(
    tenant_id: str, permissions: frozenset[Permission], trace_id: str | None = None
) -> RequestContext:
    return RequestContext(
        tenant_id=tenant_id,
        actor_id=ACTOR_ID,
        role="system",
        correlation_id=str(uuid4()),
        permissions=permissions,
        trace_id=trace_id,
    )


_CONTROL = frozenset({Permission.JOBS_MANAGE})


async def _run_one(
    factory: async_sessionmaker[AsyncSession], tenant_id: str
) -> bool:
    """Claim and execute one job for a tenant; return False when nothing was ready."""
    async with factory() as session:
        claim_context = _context(tenant_id, _CONTROL)
        job_types = set(HANDLERS)
        if "connectors" in await disabled_flags(session, tenant_id):
            # Left queued, not failed, so the work resumes when the switch is turned back on.
            job_types -= CONNECTOR_JOB_TYPES
        if connector_breaker.blocked():
            job_types -= CONNECTOR_JOB_TYPES
        job = await claim_next_job(
            session,
            claim_context,
            queue=QUEUE,
            worker_id=WORKER_ID,
            lease_seconds=settings.job_default_lease_seconds,
            # Types without a handler stay queued for external workers.
            job_types=job_types,
        )
        if job is None:
            return False
        job_id, job_type, timeout_seconds = job.id, job.job_type, job.timeout_seconds
        provider = None
        if job_type in CONNECTOR_JOB_TYPES:
            provider = await _job_provider(session, tenant_id, job)
            connector_breaker.start_probe(provider)
        trace_id = job.trace_id or uuid4().hex
        claim_context = _context(tenant_id, _CONTROL, trace_id)
        await heartbeat_job(
            session, claim_context, job_id, WORKER_ID, timeout_seconds + LEASE_GRACE_SECONDS
        )
        entry = HANDLERS.get(job_type)
        if entry is None:
            await fail_job(
                session,
                claim_context,
                job_id,
                WORKER_ID,
                JobFailureRequest(
                    error_code="no_handler",
                    error_detail=f"No handler for job type {job_type}",
                    retryable=False,
                ),
            )
            return True
        handler, permissions = entry
        timeout_scope = asyncio.timeout(timeout_seconds)
        try:
            # The handler gets its own session so a timeout cancelling it mid-query cannot
            # leave the claim session (used for complete/fail) in an unknown state.
            async with timeout_scope, factory() as handler_session:
                result = await handler(
                    handler_session, _context(tenant_id, permissions, trace_id), job
                )
        except Exception as error:
            timed_out = isinstance(error, TimeoutError) and timeout_scope.expired()
            if provider is not None:
                if isinstance(error, SyncFailedError) or timed_out:
                    connector_breaker.record_failure(provider)
                else:
                    connector_breaker.release(provider)
            code = "job_timeout" if timed_out else type(error).__name__
            retryable = isinstance(error, CapabilityDisabledError) or not (
                isinstance(error, InvalidRequestError)
                or (isinstance(error, DomainError) and not isinstance(error, ConflictError))
            )
            await fail_job(
                session,
                claim_context,
                job_id,
                WORKER_ID,
                JobFailureRequest(
                    error_code=code[:100], error_detail=str(error)[:500], retryable=retryable
                ),
            )
            return True
        if provider is not None:
            connector_breaker.record_success(provider)
        await complete_job(session, claim_context, job_id, WORKER_ID, result)
        return True


async def enqueue_scheduled_syncs(
    factory: async_sessionmaker[AsyncSession], tenant_id: str, now: datetime
) -> int:
    """Enqueue one incremental sync per healthy connection for the current interval bucket."""
    bucket = int(now.timestamp()) // settings.integration_sync_interval_seconds
    async with factory() as session:
        if not await is_enabled(session, tenant_id, "connectors"):
            return 0
        connections = list(
            await session.execute(
                select(IntegrationConnection.id, IntegrationConnection.token_expires_at).where(
                    IntegrationConnection.tenant_id == tenant_id,
                    IntegrationConnection.status == "connected",
                )
            )
        )
        refresh_context = _context(tenant_id, frozenset({Permission.INTEGRATIONS_MANAGE}))
        enqueued = 0
        for connection_id, expires_at in connections:
            try:
                latest = (
                    await session.execute(
                        select(
                            IntegrationSyncRun.status,
                            IntegrationSyncRun.next_retry_at,
                            IntegrationSyncRun.failure_code,
                        )
                        .where(IntegrationSyncRun.connection_id == connection_id)
                        .order_by(IntegrationSyncRun.created_at.desc())
                        .limit(1)
                    )
                ).first()
                if latest is not None and latest.status == "failed":
                    permanent = latest.failure_code not in TRANSIENT_PROVIDER_CODES
                    backing_off = (
                        latest.next_retry_at is not None and _aware(latest.next_retry_at) > now
                    )
                    if permanent or backing_off:
                        continue
                if expires_at is not None and _aware(expires_at) <= now:
                    # Permanent refresh failures flip the connection to needs_reauth, which
                    # the proactive checks turn into an alert; transient ones retry next interval.
                    try:
                        await refresh_connection(session, refresh_context, connection_id)
                    except ConnectorProviderError:
                        continue
                await create_job(
                    session,
                    _context(tenant_id, _CONTROL, uuid4().hex),
                    JobCreate(
                        job_type="integration.sync",
                        payload={"connection_id": connection_id, "mode": "incremental"},
                    ),
                    f"sync:{connection_id}:{bucket}",
                )
                enqueued += 1
            except BackpressureError:
                await session.rollback()
                logger.warning("job backlog full for tenant %s; sync scheduling skipped", tenant_id)
                break
            except Exception:
                await session.rollback()
                logger.exception("could not schedule sync for connection %s", connection_id)
    return enqueued


async def tenants_with_work(factory: async_sessionmaker[AsyncSession], now: datetime) -> set[str]:
    """Tenants the per-tenant pass would act on this tick: claimable ready jobs, running jobs
    whose lease or timeout has passed, and agent runs past their deadline.

    Deliberately cross-tenant (the worker already lists every tenant) and index-backed, so an
    idle tick costs a couple of queries instead of several per tenant. Ready jobs the worker
    cannot claim do not make a tenant busy: types without a handler (they wait for external
    workers), and connector jobs held back by the platform kill switch, a tenant kill switch or
    an open circuit breaker. Expired leases are always discovered, whatever the queue or type,
    because reconciliation is not limited to claimable jobs."""
    claimable_types = set(HANDLERS)
    if connector_breaker.blocked() or "connectors" in settings.disabled_capability_set:
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


def _rotated(tenant_ids: list[str], start_offset: int | None) -> list[str]:
    """Order tenants for this tick. With no explicit offset, start after the tenant that went
    first last time, so rotation stays fair even though the busy set changes between ticks."""
    global _last_start
    if not tenant_ids:
        return tenant_ids
    if start_offset is not None:
        pivot = start_offset % len(tenant_ids)
    else:
        pivot = next(
            (
                index
                for index, name in enumerate(tenant_ids)
                if _last_start is None or name > _last_start
            ),
            0,
        )
        _last_start = tenant_ids[pivot]
    return tenant_ids[pivot:] + tenant_ids[:pivot]


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
            await reconcile_expired_jobs(session, _context(tenant_id, _CONTROL))
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
            await expire_overdue_runs(session, _context(tenant_id, frozenset()))
        if run_proactive:
            async with factory() as session:
                await run_proactive_checks(
                    session,
                    _context(tenant_id, frozenset({Permission.OBSERVABILITY_MANAGE})),
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
    if run_proactive or schedule_syncs:
        async with factory() as session:
            tenant_ids = sorted(await session.scalars(select(Organization.id)))
    else:
        tenant_ids = sorted(await tenants_with_work(factory, utc_now()))
    handled = 0
    for tenant_id in _rotated(tenant_ids, start_offset):
        handled += await _visit_tenant(
            factory,
            tenant_id,
            run_proactive=run_proactive,
            schedule_syncs=schedule_syncs,
            failures=failures,
        )
    return handled


def _elapsed(last: datetime | None, now: datetime, seconds: float) -> bool:
    return last is None or (now - last).total_seconds() >= seconds


async def run_forever(
    factory: async_sessionmaker[AsyncSession], stop_event: asyncio.Event
) -> None:
    last_proactive: datetime | None = None
    last_sync_schedule: datetime | None = None
    while not stop_event.is_set():
        now = utc_now()
        due = _elapsed(last_proactive, now, settings.proactive_check_interval_seconds)
        sync_due = _elapsed(last_sync_schedule, now, settings.integration_sync_interval_seconds)
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
