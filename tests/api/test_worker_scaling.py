import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_crm.config import settings
from ai_crm.models import DurableJob
from ai_crm.permissions import Permission
from ai_crm.work import handlers as handlers_module
from ai_crm.work import runner as runner_module
from ai_crm.work.breaker import CircuitBreaker
from ai_crm.work.handlers import SyncFailedError
from ai_crm.work.runner import run_tick
from tests.api.test_worker import create_job, get_job, tenant_headers

Factory = async_sessionmaker[AsyncSession]
API = "/api/v1"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# --- breaker unit ----------------------------------------------------------------------------


def test_breaker_opens_cools_down_probes_and_closes() -> None:
    clock = Clock()
    breaker = CircuitBreaker(threshold=3, cooldown_seconds=60, clock=clock)

    breaker.record_failure("p")
    breaker.record_failure("p")
    assert not breaker.is_open("p")
    breaker.record_failure("p")
    assert breaker.is_open("p") and breaker.blocked() and breaker.open_keys() == ["p"]

    clock.now = 59
    assert breaker.is_open("p")
    clock.now = 61  # half-open: the next job is allowed through as a probe
    assert not breaker.is_open("p")
    breaker.record_failure("p")  # a failed probe re-opens for a full cooldown
    assert breaker.is_open("p")
    clock.now = 125
    breaker.record_success("p")
    assert not breaker.is_open("p") and not breaker.blocked()


def test_breaker_success_resets_the_failure_count_and_keys_are_independent() -> None:
    breaker = CircuitBreaker(threshold=2, cooldown_seconds=60, clock=Clock())
    breaker.record_failure("a")
    breaker.record_success("a")
    breaker.record_failure("a")
    breaker.record_failure("b")
    breaker.record_failure("b")

    assert not breaker.is_open("a") and breaker.is_open("b")


# --- breaker wired into the worker -----------------------------------------------------------


async def make_connection(client: AsyncClient, tenant: str = "tenant-a") -> str:
    response = await client.post(
        f"{API}/integrations/connections",
        headers=tenant_headers(tenant),
        json={
            "provider_key": "fixture",
            "external_account_id": f"acct-{tenant}",
            "scopes": ["activities:read"],
            "secret_ref": "fixture-secret",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_open_breaker_keeps_connector_jobs_queued_until_cooldown(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    monkeypatch.setattr(
        runner_module, "connector_breaker", CircuitBreaker(2, 60, clock=clock)
    )
    monkeypatch.setattr(settings, "worker_batch_size", 1)
    outcome = {"fail": True}

    async def flaky(session, context, job):
        if outcome["fail"]:
            raise SyncFailedError("provider down")
        return {"ok": True}

    monkeypatch.setitem(
        handlers_module.HANDLERS,
        "integration.sync",
        (flaky, frozenset({Permission.INTEGRATIONS_SYNC})),
    )
    connection_id = await make_connection(client)
    jobs = [
        await create_job(
            client,
            "integration.sync",
            {"connection_id": connection_id},
            key=f"sync-{index}",
            max_attempts=5,
        )
        for index in range(3)
    ]

    await run_tick(session_factory)
    await run_tick(session_factory)
    assert runner_module.connector_breaker.is_open("fixture")
    handled_while_open = await run_tick(session_factory)
    third = await get_job(session_factory, jobs[2]["id"])

    assert handled_while_open == 0
    assert third.status == "queued" and third.attempts == 0

    outcome["fail"] = False
    clock.now = 61
    await run_tick(session_factory)

    assert not runner_module.connector_breaker.is_open("fixture")


async def test_permanent_failures_do_not_trip_the_breaker(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_module, "connector_breaker", CircuitBreaker(1, 60, clock=Clock()))

    async def permanent(session, context, job):
        raise ValueError("bad payload")

    monkeypatch.setitem(
        handlers_module.HANDLERS,
        "integration.sync",
        (permanent, frozenset({Permission.INTEGRATIONS_SYNC})),
    )
    connection_id = await make_connection(client)
    await create_job(client, "integration.sync", {"connection_id": connection_id}, key="p")

    await run_tick(session_factory)

    assert not runner_module.connector_breaker.blocked()


# --- fairness --------------------------------------------------------------------------------


async def test_tenant_order_rotates_every_tick(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []

    async def record(session, context, job):
        order.append(context.tenant_id)
        return {}

    monkeypatch.setitem(
        handlers_module.HANDLERS, "notification.send", (record, frozenset({Permission.WORK_MANAGE}))
    )
    monkeypatch.setattr(runner_module, "_tick_counter", 0)
    for tenant in ("tenant-a", "tenant-b"):
        for index in range(2):
            await create_job(
                client, "notification.send", {}, key=f"{tenant}-{index}", tenant_id=tenant
            )

    await run_tick(session_factory)
    await run_tick(session_factory)

    assert order[0] == "tenant-a" and order[2] == "tenant-b"


async def test_time_budget_moves_on_to_the_next_tenant(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    handled: list[str] = []

    async def slow(session, context, job):
        handled.append(context.tenant_id)
        await asyncio.sleep(0.02)
        return {}

    monkeypatch.setitem(
        handlers_module.HANDLERS, "notification.send", (slow, frozenset({Permission.WORK_MANAGE}))
    )
    monkeypatch.setattr(settings, "worker_tenant_time_budget_seconds", 0.001)
    for tenant in ("tenant-a", "tenant-b"):
        for index in range(3):
            await create_job(
                client, "notification.send", {}, key=f"{tenant}-{index}", tenant_id=tenant
            )

    await run_tick(session_factory, start_offset=0)

    assert handled == ["tenant-a", "tenant-b"]


# --- backpressure ----------------------------------------------------------------------------


async def post_job(client: AsyncClient, key: str, tenant: str = "tenant-a"):
    return await client.post(
        f"{API}/jobs",
        headers={**tenant_headers(tenant), "Idempotency-Key": key},
        json={"job_type": "notification.send", "payload": {}, "backoff_seconds": 0},
    )


async def test_full_backlog_returns_429_but_duplicates_and_other_tenants_pass(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_queued_jobs_per_tenant", 2)
    assert (await post_job(client, "k1")).status_code == 201
    assert (await post_job(client, "k2")).status_code == 201

    shed = await post_job(client, "k3")
    duplicate = await post_job(client, "k1")
    other_tenant = await post_job(client, "k1", "tenant-b")

    assert shed.status_code == 429
    assert shed.json()["code"] == "backpressure"
    assert shed.headers["Retry-After"] == "30"
    assert duplicate.status_code == 201
    assert other_tenant.status_code == 201


async def test_finishing_jobs_frees_backlog_capacity(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok(session, context, job):
        return {}

    monkeypatch.setitem(
        handlers_module.HANDLERS, "notification.send", (ok, frozenset({Permission.WORK_MANAGE}))
    )
    monkeypatch.setattr(settings, "max_queued_jobs_per_tenant", 1)
    assert (await post_job(client, "k1")).status_code == 201
    assert (await post_job(client, "k2")).status_code == 429

    await run_tick(session_factory)

    assert (await post_job(client, "k2")).status_code == 201


async def test_scheduled_sync_skips_instead_of_failing_when_backlog_is_full(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    monkeypatch.setattr(settings, "max_queued_jobs_per_tenant", 1)
    await make_connection(client)
    assert (await post_job(client, "fill")).status_code == 201

    enqueued = await runner_module.enqueue_scheduled_syncs(
        session_factory, "tenant-a", datetime.now(UTC)
    )

    assert enqueued == 0
    async with session_factory() as session:
        from sqlalchemy import func, select

        count = await session.scalar(select(func.count()).select_from(DurableJob))
    assert count == 1


def test_half_open_admits_one_probe_and_a_lost_probe_expires() -> None:
    clock = Clock()
    breaker = CircuitBreaker(threshold=1, cooldown_seconds=60, clock=clock)
    breaker.record_failure("p")
    assert breaker.blocked()

    clock.now = 61
    assert not breaker.blocked()  # cooled down: one job may probe
    breaker.start_probe("p")
    assert breaker.blocked()  # the probe is in flight; no second job
    breaker.release("p")  # permanent error: no verdict, stay half-open
    assert not breaker.blocked()

    breaker.start_probe("p")
    assert breaker.blocked()
    clock.now = 125  # the probe never reported back
    assert not breaker.blocked()


async def test_half_open_runs_a_single_probe_per_batch_and_timeouts_trip_it(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    monkeypatch.setattr(runner_module, "connector_breaker", CircuitBreaker(1, 60, clock=clock))
    calls: list[str] = []

    async def hang(session, context, job):
        calls.append(job.id)
        await asyncio.sleep(5)

    monkeypatch.setitem(
        handlers_module.HANDLERS,
        "integration.sync",
        (hang, frozenset({Permission.INTEGRATIONS_SYNC})),
    )
    real_timeout = asyncio.timeout
    monkeypatch.setattr(runner_module.asyncio, "timeout", lambda _: real_timeout(0.05))
    connection_id = await make_connection(client)
    for index in range(4):
        await create_job(
            client, "integration.sync", {"connection_id": connection_id}, key=f"h{index}",
            max_attempts=9,
        )

    await run_tick(session_factory)  # a timeout counts as a failure and opens the breaker
    assert runner_module.connector_breaker.is_open("fixture") and len(calls) == 1

    clock.now = 61
    await run_tick(session_factory)  # half-open: exactly one probe despite a batch of 10

    assert len(calls) == 2
    assert runner_module.connector_breaker.is_open("fixture")
