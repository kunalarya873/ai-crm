from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_crm.config import settings
from ai_crm.models import AgentRun, DurableJob
from ai_crm.permissions import Permission
from ai_crm.work import handlers as handlers_module
from ai_crm.work import runner as runner_module
from ai_crm.work.runner import run_tick, tenants_with_work
from tests.api.agent_helpers import headers, make_agent, start
from tests.api.test_worker import create_job, get_job

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
def noop_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok(session, context, job):
        return {"ok": True}

    monkeypatch.setitem(
        handlers_module.HANDLERS, "notification.send", (ok, frozenset({Permission.WORK_MANAGE}))
    )


@pytest.fixture
def visits(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    real = runner_module.reconcile_expired_jobs

    async def spy(session, context):
        seen.append(context.tenant_id)
        return await real(session, context)

    monkeypatch.setattr(runner_module, "reconcile_expired_jobs", spy)
    return seen


async def test_idle_tenants_are_not_visited(
    client: AsyncClient, session_factory: Factory, noop_handler: None, visits: list[str]
) -> None:
    await run_tick(session_factory)
    assert visits == []

    job = await create_job(client, "notification.send", {}, key="d1", tenant_id="tenant-b")
    handled = await run_tick(session_factory)

    assert handled == 1 and visits == ["tenant-b"]
    assert (await get_job(session_factory, job["id"])).status == "succeeded"


async def test_future_and_backoff_jobs_are_not_visited_until_due(
    client: AsyncClient, session_factory: Factory, noop_handler: None, visits: list[str]
) -> None:
    later = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    scheduled = await create_job(
        client, "notification.send", {}, key="d2", run_at=later
    )
    await run_tick(session_factory)
    assert visits == []

    async with session_factory() as session:
        await session.execute(
            update(DurableJob)
            .where(DurableJob.id == scheduled["id"])
            .values(run_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    await run_tick(session_factory)

    assert visits == ["tenant-a"]
    assert (await get_job(session_factory, scheduled["id"])).status == "succeeded"

    backoff = await create_job(client, "notification.send", {}, key="d3")
    async with session_factory() as session:
        await session.execute(
            update(DurableJob)
            .where(DurableJob.id == backoff["id"])
            .values(status="retryable", next_attempt_at=datetime.now(UTC) + timedelta(hours=1))
        )
        await session.commit()
    visits.clear()
    await run_tick(session_factory)

    assert visits == []


async def test_expired_lease_is_discovered_and_reconciled(
    client: AsyncClient, session_factory: Factory, noop_handler: None, visits: list[str]
) -> None:
    job = await create_job(client, "notification.send", {}, key="d4", max_attempts=3)
    async with session_factory() as session:
        await session.execute(
            update(DurableJob)
            .where(DurableJob.id == job["id"])
            .values(
                status="running",
                lease_owner="crashed",
                attempts=1,
                lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        await session.commit()

    assert await tenants_with_work(session_factory, datetime.now(UTC)) == {"tenant-a"}
    await run_tick(session_factory)

    assert visits == ["tenant-a"]
    assert (await get_job(session_factory, job["id"])).status == "succeeded"


async def test_overdue_agent_run_is_discovered_and_failed(
    client: AsyncClient, session_factory: Factory
) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent, objective="late")
    assert await tenants_with_work(session_factory, datetime.now(UTC)) == set()
    async with session_factory() as session:
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id == run["id"])
            .values(deadline_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()

    assert await tenants_with_work(session_factory, datetime.now(UTC)) == {"tenant-a"}
    await run_tick(session_factory)

    async with session_factory() as session:
        stored = await session.get_one(AgentRun, run["id"])
    assert stored.status == "failed" and stored.terminal_reason == "deadline_exceeded"
    assert await tenants_with_work(session_factory, datetime.now(UTC)) == set()


async def test_job_types_without_a_handler_do_not_make_a_tenant_busy(
    client: AsyncClient, session_factory: Factory
) -> None:
    await create_job(client, "reminder.dispatch", {}, key="d5")

    assert await tenants_with_work(session_factory, datetime.now(UTC)) == set()


async def test_interval_ticks_still_visit_every_tenant(
    client: AsyncClient, session_factory: Factory, visits: list[str]
) -> None:
    await run_tick(session_factory, schedule_syncs=True)
    assert sorted(visits) == ["tenant-a", "tenant-b"]

    visits.clear()
    await run_tick(session_factory, run_proactive=True)
    assert sorted(visits) == ["tenant-a", "tenant-b"]


async def test_one_failing_tenant_does_not_stop_the_others(
    client: AsyncClient,
    session_factory: Factory,
    noop_handler: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = runner_module.reconcile_expired_jobs

    async def flaky(session, context):
        if context.tenant_id == "tenant-a":
            raise RuntimeError("db hiccup")
        return await real(session, context)

    monkeypatch.setattr(runner_module, "reconcile_expired_jobs", flaky)
    monkeypatch.setattr(settings, "worker_batch_size", 1)
    await create_job(client, "notification.send", {}, key="d6", tenant_id="tenant-a")
    other = await create_job(client, "notification.send", {}, key="d7", tenant_id="tenant-b")
    failures: list[str] = []

    await run_tick(session_factory, failures=failures)

    assert failures == ["tenant-a"]
    assert (await get_job(session_factory, other["id"])).status == "succeeded"


async def test_expired_lease_on_a_job_without_a_handler_is_still_reconciled(
    client: AsyncClient, session_factory: Factory, visits: list[str]
) -> None:
    """Reconciliation is not limited to claimable jobs: an external worker that crashed holding
    a reminder job must still be cleaned up promptly."""
    job = await create_job(client, "reminder.dispatch", {}, key="d8", max_attempts=3)
    async with session_factory() as session:
        await session.execute(
            update(DurableJob)
            .where(DurableJob.id == job["id"])
            .values(
                status="running",
                lease_owner="external",
                attempts=1,
                lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        await session.commit()

    await run_tick(session_factory)

    assert visits == ["tenant-a"]
    assert (await get_job(session_factory, job["id"])).status == "retryable"


async def test_connector_jobs_held_back_do_not_make_a_tenant_busy(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_crm.work.breaker import CircuitBreaker

    await create_job(client, "integration.sync", {"connection_id": "c1"}, key="d9")
    now = datetime.now(UTC)
    assert await tenants_with_work(session_factory, now) == {"tenant-a"}

    breaker = CircuitBreaker(1, 60)
    breaker.record_failure("fixture")
    monkeypatch.setattr(runner_module, "connector_breaker", breaker)
    assert await tenants_with_work(session_factory, now) == set()

    monkeypatch.setattr(runner_module, "connector_breaker", CircuitBreaker(1, 60))
    monkeypatch.setattr(settings, "disabled_capabilities", "connectors")
    assert await tenants_with_work(session_factory, now) == set()
    monkeypatch.setattr(settings, "disabled_capabilities", "")

    switch = await client.put(
        "/api/v1/admin/feature-flags/connectors",
        headers={**headers("user-d"), "If-Match": '"0"'},
        json={"enabled": False, "reason": "incident"},
    )
    assert switch.status_code == 200, switch.text
    assert await tenants_with_work(session_factory, now) == set()


async def test_rotation_stays_fair_when_the_busy_set_changes(
    client: AsyncClient,
    session_factory: Factory,
    noop_handler: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    real = runner_module.reconcile_expired_jobs

    async def spy(session, context):
        order.append(context.tenant_id)
        return await real(session, context)

    monkeypatch.setattr(runner_module, "reconcile_expired_jobs", spy)
    monkeypatch.setattr(runner_module, "_last_start", None)
    monkeypatch.setattr(settings, "worker_batch_size", 1)
    firsts = []
    for round_number in range(4):
        for tenant in ("tenant-a", "tenant-b"):
            await create_job(
                client, "notification.send", {}, key=f"r{round_number}-{tenant}", tenant_id=tenant
            )
        order.clear()
        await run_tick(session_factory)
        firsts.append(order[0])

    assert firsts == ["tenant-a", "tenant-b", "tenant-a", "tenant-b"]
