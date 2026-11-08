from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_crm.config import settings
from ai_crm.models import ActionExecution, AgentRun, AIRun, DurableJob, IntegrationSyncRun
from tests.api.agent_helpers import API, headers, make_agent, start

Factory = async_sessionmaker[AsyncSession]
UNMEASURED = {"api_availability", "api_latency_p95_ms", "api_error_rate"}


async def slos(
    client: AsyncClient, user: str = "user-d", tenant: str = "tenant-a"
) -> dict[str, dict[str, Any]]:
    response = await client.get(f"{API}/observability/slos", headers=headers(user, tenant))
    assert response.status_code == 200, response.text
    return {item["key"]: item for item in response.json()["slos"]}


async def add_job(
    factory: Factory, status: str, *, key: str, run_at: datetime, tenant: str = "tenant-a"
) -> None:
    async with factory() as session:
        session.add(
            DurableJob(
                tenant_id=tenant,
                idempotency_key=key,
                request_hash="h",
                job_type="notification.send",
                status=status,
                run_at=run_at,
            )
        )
        await session.commit()


async def test_empty_tenant_reports_no_data_not_a_misleading_pass(client: AsyncClient) -> None:
    result = await slos(client)

    assert result["queue_age_seconds"]["status"] == "met"
    assert result["agent_overdue_runs"]["status"] == "met"
    for key in (
        "job_success_rate",
        "sync_freshness_seconds",
        "search_freshness_ratio",
        "action_completion_rate",
        "ai_fallback_rate",
        "ai_avg_latency_ms",
    ):
        assert result[key]["status"] == "no_data", key
        assert result[key]["value"] is None


async def test_api_slos_are_never_faked_and_every_slo_has_an_owner(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_owner = await slos(client)
    monkeypatch.setattr(settings, "slo_owner", "payments-oncall")
    custom_owner = await slos(client)

    for key in UNMEASURED:
        assert default_owner[key]["status"] == "not_measured"
        assert default_owner[key]["value"] is None and default_owner[key]["reason"]
    assert {item["owner"] for item in default_owner.values()} == {"platform-oncall"}
    assert {item["owner"] for item in custom_owner.values()} == {"payments-oncall"}


async def test_queue_age_breaches_when_a_ready_job_waits_too_long(
    client: AsyncClient, session_factory: Factory
) -> None:
    now = datetime.now(UTC)
    await add_job(session_factory, "queued", key="fresh", run_at=now)
    fresh = await slos(client)
    await add_job(session_factory, "queued", key="old", run_at=now - timedelta(minutes=10))
    await add_job(
        session_factory, "queued", key="future", run_at=now + timedelta(days=1)
    )  # not ready yet
    stale = await slos(client)

    assert fresh["queue_age_seconds"]["status"] == "met"
    assert stale["queue_age_seconds"]["status"] == "breached"
    assert stale["queue_age_seconds"]["value"] >= 600


async def test_job_success_rate(client: AsyncClient, session_factory: Factory) -> None:
    now = datetime.now(UTC)
    await add_job(session_factory, "succeeded", key="a", run_at=now)
    await add_job(session_factory, "succeeded", key="b", run_at=now)
    healthy = await slos(client)
    await add_job(session_factory, "dead_letter", key="c", run_at=now)
    degraded = await slos(client)

    assert healthy["job_success_rate"]["status"] == "met"
    assert degraded["job_success_rate"]["status"] == "breached"
    assert degraded["job_success_rate"]["value"] == pytest.approx(2 / 3)


async def test_sync_freshness(client: AsyncClient, session_factory: Factory) -> None:
    created = await client.post(
        f"{API}/integrations/connections",
        headers=headers("user-d"),
        json={
            "provider_key": "fixture",
            "external_account_id": "slo-account",
            "scopes": ["activities:read"],
            "secret_ref": "fixture-secret",
        },
    )
    connection_id = created.json()["id"]
    new_connection = await slos(client)
    async with session_factory() as session:
        session.add(
            IntegrationSyncRun(
                connection_id=connection_id,
                resource_type="activity",
                mode="incremental",
                status="succeeded",
                last_success_at=datetime.now(UTC) - timedelta(hours=3),
            )
        )
        await session.commit()
    stale = await slos(client)

    assert new_connection["sync_freshness_seconds"]["status"] == "met"
    assert stale["sync_freshness_seconds"]["status"] == "breached"
    assert stale["sync_freshness_seconds"]["value"] > 3 * 3600 - 60


async def test_search_freshness(client: AsyncClient) -> None:
    for index, fresh_until in enumerate((datetime.now(UTC) - timedelta(days=1), None)):
        body: dict[str, Any] = {
            "source_type": "document",
            "source_record_id": f"doc-{index}",
            "title": "Doc",
            "content": "text",
        }
        if fresh_until:
            body["fresh_until"] = fresh_until.isoformat()
        assert (
            await client.post(f"{API}/knowledge/sources", headers=headers("user-a"), json=body)
        ).status_code == 201

    result = await slos(client)

    assert result["search_freshness_ratio"]["status"] == "breached"
    assert result["search_freshness_ratio"]["value"] == 1.0
    assert result["search_freshness_ratio"]["detail"]["sources_with_freshness"] == 1


async def test_overdue_agent_runs_breach(client: AsyncClient, session_factory: Factory) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)
    healthy = await slos(client)
    async with session_factory() as session:
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id == run["id"])
            .values(deadline_at=datetime.now(UTC) - timedelta(minutes=5))
        )
        await session.commit()
    overdue = await slos(client)

    assert healthy["agent_overdue_runs"]["status"] == "met"
    assert overdue["agent_overdue_runs"]["status"] == "breached"
    assert overdue["agent_overdue_runs"]["value"] == 1.0


async def test_slos_are_tenant_isolated_and_readable_by_viewers(
    client: AsyncClient, session_factory: Factory
) -> None:
    await add_job(
        session_factory,
        "queued",
        key="old",
        run_at=datetime.now(UTC) - timedelta(hours=1),
        tenant="tenant-b",
    )

    tenant_a = await slos(client, "user-b", "tenant-a")
    tenant_b = await slos(client, "user-d", "tenant-b")
    naive = await client.get(
        f"{API}/observability/slos",
        headers=headers("user-d"),
        params={"window_start": "2026-01-01T00:00:00", "window_end": "2026-01-02T00:00:00"},
    )

    assert tenant_a["queue_age_seconds"]["status"] == "met"
    assert tenant_b["queue_age_seconds"]["status"] == "breached"
    assert naive.status_code == 422


async def test_crashed_worker_lease_shows_up_in_queue_age(
    client: AsyncClient, session_factory: Factory
) -> None:
    async with session_factory() as session:
        session.add(
            DurableJob(
                tenant_id="tenant-a",
                idempotency_key="crashed",
                request_hash="h",
                job_type="notification.send",
                status="running",
                lease_expires_at=datetime.now(UTC) - timedelta(minutes=20),
                run_at=datetime.now(UTC) - timedelta(minutes=30),
            )
        )
        await session.commit()

    result = await slos(client)

    assert result["queue_age_seconds"]["status"] == "breached"
    assert result["queue_age_seconds"]["detail"]["abandoned_leases"] is True


async def test_action_completion_counts_only_finished_executions(
    client: AsyncClient, session_factory: Factory
) -> None:
    async with session_factory() as session:
        for index, status in enumerate(["executing"] * 19 + ["failed"]):
            session.add(
                ActionExecution(
                    tenant_id="tenant-a",
                    action_proposal_id=f"p{index}",
                    idempotency_key=f"k{index}",
                    action_type="task.create",
                    request_hash="h",
                    status=status,
                )
            )
        await session.commit()

    result = await slos(client)

    # 19 still running must not count as successes: 0 of 1 finished succeeded.
    assert result["action_completion_rate"]["status"] == "breached"
    assert result["action_completion_rate"]["value"] == 0.0
    assert result["action_completion_rate"]["detail"]["finished_executions"] == 1


async def test_ai_rates_and_window_limit(client: AsyncClient, session_factory: Factory) -> None:
    async with session_factory() as session:
        for index, (status, latency) in enumerate([("succeeded", 100), ("fallback", 300)]):
            session.add(
                AIRun(
                    tenant_id="tenant-a",
                    actor_id="user-a",
                    idempotency_key=f"ai{index}",
                    request_hash="h",
                    use_case="customer_summary",
                    provider_key="fixture",
                    model_key="m",
                    config_version="c",
                    prompt_version="v",
                    prompt_hash="p",
                    status=status,
                    latency_ms=latency,
                )
            )
        await session.commit()

    result = await slos(client)
    too_wide = await client.get(
        f"{API}/observability/slos",
        headers=headers("user-d"),
        params={"window_start": "2020-01-01T00:00:00Z", "window_end": "2026-01-01T00:00:00Z"},
    )

    assert result["ai_fallback_rate"]["value"] == 0.5
    assert result["ai_fallback_rate"]["status"] == "breached"
    assert result["ai_avg_latency_ms"]["value"] == 200.0
    assert result["ai_avg_latency_ms"]["status"] == "met"
    assert too_wide.status_code == 422


async def test_sync_target_follows_the_setting_and_names_the_worst_connection(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await client.post(
        f"{API}/integrations/connections",
        headers=headers("user-d"),
        json={
            "provider_key": "fixture",
            "external_account_id": "target-account",
            "scopes": ["activities:read"],
            "secret_ref": "fixture-secret",
        },
    )
    monkeypatch.setattr(settings, "integration_sync_interval_seconds", 7)

    result = await slos(client)

    assert result["sync_freshness_seconds"]["target"] == 14
    assert result["sync_freshness_seconds"]["detail"]["worst_connection_id"] == created.json()["id"]
