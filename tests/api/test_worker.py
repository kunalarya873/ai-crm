import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_crm import main as main_module
from ai_crm.api.deps import RequestContext
from ai_crm.auth import create_access_token
from ai_crm.config import settings
from ai_crm.models import DurableJob
from ai_crm.permissions import Permission
from ai_crm.work import handlers as handlers_module
from ai_crm.work.jobs import claim_next_job
from ai_crm.work.runner import run_tick

pytestmark = pytest.mark.asyncio

Factory = async_sessionmaker[AsyncSession]


def tenant_headers(tenant_id: str, user_id: str = "user-d") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-ID": tenant_id,
    }


async def create_job(
    client: AsyncClient,
    job_type: str,
    payload: dict[str, object],
    *,
    key: str,
    tenant_id: str = "tenant-a",
    **extra: object,
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/jobs",
        headers={**tenant_headers(tenant_id), "Idempotency-Key": key},
        json={"job_type": job_type, "payload": payload, "backoff_seconds": 0, **extra},
    )
    assert response.status_code == 201
    return response.json()


async def get_job(factory: Factory, job_id: str) -> DurableJob:
    async with factory() as session:
        return await session.get_one(DurableJob, job_id)


@pytest.fixture
def noop_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok(session, context, job):
        return {"ok": True}

    monkeypatch.setitem(
        handlers_module.HANDLERS, "notification.send", (ok, frozenset({Permission.WORK_MANAGE}))
    )


async def test_job_runs_once_and_double_tick_is_noop(
    client: AsyncClient, session_factory: Factory, noop_handler: None
) -> None:
    job = await create_job(client, "notification.send", {"reminder_id": "r-1"}, key="w-1")

    first = await run_tick(session_factory)
    second = await run_tick(session_factory)
    stored = await get_job(session_factory, job["id"])

    assert (first, second) == (1, 0)
    assert stored.status == "succeeded"
    assert stored.result == {"ok": True}
    assert stored.attempts == 1


async def test_job_types_without_a_handler_stay_queued_for_external_workers(
    client: AsyncClient, session_factory: Factory
) -> None:
    job = await create_job(client, "reminder.dispatch", {"reminder_id": "r"}, key="w-nohandler")

    handled = await run_tick(session_factory)
    stored = await get_job(session_factory, job["id"])

    assert handled == 0
    assert stored.status == "queued" and stored.attempts == 0


async def test_bad_payload_is_not_retried(client: AsyncClient, session_factory: Factory) -> None:
    job = await create_job(client, "integration.sync", {}, key="w-badpayload")

    await run_tick(session_factory)
    stored = await get_job(session_factory, job["id"])

    assert stored.status == "failed"
    assert stored.error_code == "InvalidRequestError"
    assert stored.attempts == 1


async def test_integration_sync_job_runs_through_sync_service(
    client: AsyncClient, session_factory: Factory
) -> None:
    connection = await client.post(
        "/api/v1/integrations/connections",
        headers=tenant_headers("tenant-a"),
        json={
            "provider_key": "fixture",
            "external_account_id": "worker-account",
            "scopes": ["activities:read"],
            "secret_ref": "fixture-secret",
        },
    )
    job = await create_job(
        client,
        "integration.sync",
        {"connection_id": connection.json()["id"], "mode": "initial"},
        key="w-sync",
    )

    await run_tick(session_factory)
    stored = await get_job(session_factory, job["id"])

    assert stored.status == "succeeded"
    assert stored.result["sync_run_id"]


async def test_failing_handler_retries_then_dead_letters(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(session, context, job):
        raise RuntimeError("provider exploded")

    monkeypatch.setitem(
        handlers_module.HANDLERS, "notification.send", (boom, frozenset({Permission.WORK_MANAGE}))
    )
    monkeypatch.setattr(settings, "worker_batch_size", 1)
    job = await create_job(
        client, "notification.send", {"reminder_id": "r"}, key="w-boom", max_attempts=2
    )

    await run_tick(session_factory)
    after_first = await get_job(session_factory, job["id"])
    await run_tick(session_factory)
    after_second = await get_job(session_factory, job["id"])

    assert after_first.status == "retryable"
    assert after_first.error_code == "RuntimeError"
    assert after_second.status == "dead_letter"
    assert after_second.attempts == 2


async def test_handler_timeout_error_is_not_mislabelled_as_job_timeout(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def provider_timeout(session, context, job):
        raise TimeoutError

    monkeypatch.setitem(
        handlers_module.HANDLERS,
        "notification.send",
        (provider_timeout, frozenset({Permission.WORK_MANAGE})),
    )
    job = await create_job(client, "notification.send", {}, key="w-provider-timeout")

    await run_tick(session_factory)

    assert (await get_job(session_factory, job["id"])).error_code == "TimeoutError"


async def test_slow_handler_is_cancelled_and_job_marked_job_timeout(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_crm.work import runner as runner_module

    async def slow(session, context, job):
        await asyncio.sleep(5)
        return {}

    monkeypatch.setitem(
        handlers_module.HANDLERS, "notification.send", (slow, frozenset({Permission.WORK_MANAGE}))
    )
    real_timeout = asyncio.timeout
    monkeypatch.setattr(runner_module.asyncio, "timeout", lambda _: real_timeout(0.05))
    job = await create_job(client, "notification.send", {}, key="w-slow", max_attempts=1)

    await run_tick(session_factory)
    stored = await get_job(session_factory, job["id"])

    assert stored.error_code == "job_timeout"
    assert stored.status == "dead_letter"


async def test_handlers_receive_only_their_tenant_and_scoped_permissions(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[RequestContext] = []

    async def record(session, context, job):
        seen.append(context)
        return {}

    monkeypatch.setitem(
        handlers_module.HANDLERS, "notification.send", (record, frozenset({Permission.WORK_MANAGE}))
    )
    await create_job(client, "notification.send", {"reminder_id": "a"}, key="w-a")
    await create_job(
        client, "notification.send", {"reminder_id": "b"}, key="w-b", tenant_id="tenant-b"
    )

    await run_tick(session_factory)

    assert sorted(context.tenant_id for context in seen) == ["tenant-a", "tenant-b"]
    assert all(context.permissions == {Permission.WORK_MANAGE} for context in seen)
    assert all(context.actor_id == "system:worker" for context in seen)


async def test_concurrent_claims_have_exactly_one_winner(
    client: AsyncClient, session_factory: Factory
) -> None:
    await create_job(client, "notification.send", {"reminder_id": "r"}, key="w-race")
    context = RequestContext(
        tenant_id="tenant-a",
        actor_id="system:worker",
        role="system",
        correlation_id="race",
        permissions=frozenset({Permission.JOBS_MANAGE}),
    )

    async def claim(worker_id: str) -> DurableJob | None:
        async with session_factory() as session:
            return await claim_next_job(
                session, context, queue="default", worker_id=worker_id, lease_seconds=60
            )

    results = await asyncio.gather(claim("w1"), claim("w2"))

    assert sum(result is not None for result in results) == 1


async def test_expired_lease_is_reclaimed_and_finished(
    client: AsyncClient, session_factory: Factory, noop_handler: None
) -> None:
    job = await create_job(client, "notification.send", {"reminder_id": "r"}, key="w-lease")
    async with session_factory() as session:
        await session.execute(
            update(DurableJob)
            .where(DurableJob.id == job["id"])
            .values(
                status="running",
                attempts=1,
                lease_owner="dead-worker",
                lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        await session.commit()

    await run_tick(session_factory)
    stored = await get_job(session_factory, job["id"])

    assert stored.status == "succeeded"
    assert stored.attempts == 2


async def test_proactive_checks_only_run_when_requested_and_dedupe(
    client: AsyncClient, session_factory: Factory
) -> None:
    await client.post(
        "/api/v1/work-items",
        headers=tenant_headers("tenant-a"),
        json={
            "item_type": "commitment",
            "title": "Late",
            "due_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        },
    )

    async def alert_count() -> int:
        response = await client.get(
            "/api/v1/observability/alerts", headers=tenant_headers("tenant-a")
        )
        return len(response.json())

    await run_tick(session_factory)
    before = await alert_count()
    await run_tick(session_factory, run_proactive=True)
    await run_tick(session_factory, run_proactive=True)

    assert before == 0
    assert await alert_count() == 1


async def test_worker_is_disabled_by_default_and_lifespan_starts_and_stops_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def fake_run_forever(factory, stop_event: asyncio.Event) -> None:
        events.append("started")
        await stop_event.wait()
        events.append("stopped")

    async def noop() -> None:
        return None

    monkeypatch.setattr(main_module, "run_forever", fake_run_forever)
    monkeypatch.setattr(main_module, "close_database", noop)
    monkeypatch.setattr(settings, "auto_create_tables", False)

    assert settings.worker_enabled is False
    async with main_module.lifespan(main_module.app):
        await asyncio.sleep(0)
    assert events == []

    monkeypatch.setattr(settings, "worker_enabled", True)
    async with main_module.lifespan(main_module.app):
        await asyncio.sleep(0)
    assert events == ["started", "stopped"]


async def test_job_states_unaffected_for_other_queues(
    client: AsyncClient, session_factory: Factory
) -> None:
    job = await create_job(
        client, "notification.send", {"reminder_id": "r"}, key="w-queue", queue="other"
    )

    handled = await run_tick(session_factory)

    assert handled == 0
    async with session_factory() as session:
        stored = await session.scalar(select(DurableJob).where(DurableJob.id == job["id"]))
    assert stored is not None and stored.status == "queued"


async def test_lease_is_extended_to_cover_job_timeout(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[datetime] = []

    async def inspect(session, context, job):
        stored = await session.get_one(DurableJob, job.id)
        assert stored.lease_expires_at is not None
        observed.append(stored.lease_expires_at)
        return {}

    monkeypatch.setitem(
        handlers_module.HANDLERS,
        "notification.send",
        (inspect, frozenset({Permission.WORK_MANAGE})),
    )
    monkeypatch.setattr(settings, "job_default_lease_seconds", 1)
    await create_job(client, "notification.send", {}, key="w-lease-ext", timeout_seconds=300)

    await run_tick(session_factory)

    lease = observed[0]
    lease = lease if lease.tzinfo else lease.replace(tzinfo=UTC)
    assert lease > datetime.now(UTC) + timedelta(seconds=200)


async def test_one_tenant_failure_does_not_stop_other_tenants(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_crm.work import runner as runner_module

    real = runner_module.reconcile_expired_jobs

    async def flaky(session, context):
        if context.tenant_id == "tenant-a":
            raise RuntimeError("tenant-a is broken")
        return await real(session, context)

    async def ok(session, context, job):
        return {"ok": True}

    monkeypatch.setattr(runner_module, "reconcile_expired_jobs", flaky)
    monkeypatch.setitem(
        handlers_module.HANDLERS, "notification.send", (ok, frozenset({Permission.WORK_MANAGE}))
    )
    job_a = await create_job(client, "notification.send", {}, key="w-iso-a")
    job_b = await create_job(client, "notification.send", {}, key="w-iso-b", tenant_id="tenant-b")

    handled = await run_tick(session_factory)

    assert handled == 1
    assert (await get_job(session_factory, job_a["id"])).status == "queued"
    assert (await get_job(session_factory, job_b["id"])).status == "succeeded"


# --- integration sync, webhook and scheduler behaviour -------------------------------------


async def make_connection(
    client: AsyncClient,
    account: str,
    *,
    tenant_id: str = "tenant-a",
    secret: str = "s3cret",
    configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/integrations/connections",
        headers=tenant_headers(tenant_id),
        json={
            "provider_key": "fixture",
            "external_account_id": account,
            "scopes": ["activities:read"],
            "secret_ref": secret,
            "configuration": configuration or {},
        },
    )
    assert response.status_code == 201
    return response.json()


async def send_webhook(
    client: AsyncClient,
    account: str,
    event_id: str,
    *,
    secret: str = "s3cret",
    timestamp: str | None = None,
) -> Any:
    import hashlib
    import hmac
    import json

    body = json.dumps(
        {
            "id": event_id,
            "type": "activity.updated",
            "timestamp": timestamp or datetime.now(UTC).isoformat(),
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return await client.post(
        "/api/v1/integrations/webhooks/fixture",
        headers={
            "X-Integration-Account": account,
            "X-Webhook-Signature": f"sha256={signature}",
            "Content-Type": "application/json",
        },
        content=body,
    )


async def jobs_of_type(factory: Factory, job_type: str) -> list[DurableJob]:
    async with factory() as session:
        statement = select(DurableJob).where(DurableJob.job_type == job_type)
        return list(await session.scalars(statement))


async def webhook_event(factory: Factory, provider_event_id: str):
    from ai_crm.models import WebhookEvent

    async with factory() as session:
        return await session.scalar(
            select(WebhookEvent).where(WebhookEvent.provider_event_id == provider_event_id)
        )


def fail_listing(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    from ai_crm.integrations import CONNECTORS, ConnectorProviderError

    async def broken(connection, cursor):
        raise ConnectorProviderError(code, f"fixture {code}")

    monkeypatch.setattr(CONNECTORS["fixture"], "list_activities", broken)


async def test_webhook_enqueues_one_job_and_tick_marks_event_processed(
    client: AsyncClient, session_factory: Factory
) -> None:
    await make_connection(client, "wh-account")

    stamp = datetime.now(UTC).isoformat()
    first = await send_webhook(client, "wh-account", "evt-1", timestamp=stamp)
    replay = await send_webhook(client, "wh-account", "evt-1", timestamp=stamp)
    invalid = await client.post(
        "/api/v1/integrations/webhooks/fixture",
        headers={"X-Integration-Account": "wh-account", "X-Webhook-Signature": "sha256=bad"},
        content=b"{}",
    )
    queued = await jobs_of_type(session_factory, "integration.webhook")
    await run_tick(session_factory)
    event = await webhook_event(session_factory, "evt-1")

    assert first.status_code == 202 and replay.status_code == 202
    assert invalid.status_code == 401
    assert len(queued) == 1
    assert event is not None and event.status == "processed" and event.processed_at is not None
    assert (await get_job(session_factory, queued[0].id)).status == "succeeded"


async def test_webhook_with_permanent_sync_failure_marks_event_failed(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_connection(client, "wh-bad")
    await send_webhook(client, "wh-bad", "evt-bad")
    fail_listing(monkeypatch, "invalid_account")

    await run_tick(session_factory)
    event = await webhook_event(session_factory, "evt-bad")
    job = (await jobs_of_type(session_factory, "integration.webhook"))[0]

    assert event is not None and event.status == "failed"
    assert event.failure_code == "InvalidRequestError"
    assert (await get_job(session_factory, job.id)).status == "failed"


async def test_webhook_with_transient_failure_retries_then_fails_event(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_connection(client, "wh-flaky")
    await send_webhook(client, "wh-flaky", "evt-flaky")
    fail_listing(monkeypatch, "rate_limit")
    monkeypatch.setattr(settings, "worker_batch_size", 1)
    job = (await jobs_of_type(session_factory, "integration.webhook"))[0]
    async with session_factory() as session:
        await session.execute(
            update(DurableJob)
            .where(DurableJob.id == job.id)
            .values(max_attempts=2, backoff_seconds=0)
        )
        await session.commit()

    await run_tick(session_factory)
    mid = await webhook_event(session_factory, "evt-flaky")
    await run_tick(session_factory)
    final = await webhook_event(session_factory, "evt-flaky")

    assert mid is not None and mid.status == "queued"
    assert final is not None and final.status == "failed"
    assert (await get_job(session_factory, job.id)).status == "dead_letter"


async def test_failed_sync_run_schedules_retry_and_transient_job_dead_letters(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_crm.models import IntegrationSyncRun

    connection = await make_connection(client, "sync-flaky")
    fail_listing(monkeypatch, "timeout")
    monkeypatch.setattr(settings, "worker_batch_size", 1)
    job = await create_job(
        client,
        "integration.sync",
        {"connection_id": connection["id"]},
        key="sync-flaky-1",
        max_attempts=2,
    )

    await run_tick(session_factory)
    first = await get_job(session_factory, job["id"])
    await run_tick(session_factory)
    second = await get_job(session_factory, job["id"])
    async with session_factory() as session:
        runs = list(await session.scalars(select(IntegrationSyncRun)))

    assert first.status == "retryable" and first.error_code == "SyncFailedError"
    assert second.status == "dead_letter"
    assert runs and all(run.status == "failed" and run.next_retry_at for run in runs)


async def test_non_transient_sync_failure_is_not_retried(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await make_connection(client, "sync-hard")
    fail_listing(monkeypatch, "permission_denied")
    job = await create_job(
        client, "integration.sync", {"connection_id": connection["id"]}, key="sync-hard-1"
    )

    await run_tick(session_factory)
    stored = await get_job(session_factory, job["id"])

    assert stored.status == "failed" and stored.attempts == 1


async def test_scheduled_sync_is_deduplicated_and_skips_unhealthy_connections(
    client: AsyncClient, session_factory: Factory
) -> None:
    from ai_crm.work.runner import enqueue_scheduled_syncs

    healthy = await make_connection(client, "sched-ok")
    disconnected = await make_connection(client, "sched-off")
    revoked = await make_connection(client, "sched-revoked")
    other_tenant = await make_connection(client, "sched-b", tenant_id="tenant-b")
    for connection, action in ((disconnected, "disconnect"), (revoked, "revoke")):
        await client.post(
            f"/api/v1/integrations/connections/{connection['id']}/{action}",
            headers=tenant_headers("tenant-a"),
        )
    now = datetime.now(UTC)

    first = await enqueue_scheduled_syncs(session_factory, "tenant-a", now)
    second = await enqueue_scheduled_syncs(session_factory, "tenant-a", now)
    await enqueue_scheduled_syncs(session_factory, "tenant-b", now)
    jobs = await jobs_of_type(session_factory, "integration.sync")

    assert (first, second) == (1, 1)
    by_tenant = {(job.tenant_id, job.payload["connection_id"]) for job in jobs}
    assert by_tenant == {("tenant-a", healthy["id"]), ("tenant-b", other_tenant["id"])}


async def expire(factory: Factory, connection_id: str) -> None:
    from ai_crm.models import IntegrationConnection

    async with factory() as session:
        await session.execute(
            update(IntegrationConnection)
            .where(IntegrationConnection.id == connection_id)
            .values(token_expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()


async def connection_row(factory: Factory, connection_id: str):
    from ai_crm.models import IntegrationConnection

    async with factory() as session:
        return await session.get_one(IntegrationConnection, connection_id)


async def test_expired_connection_is_refreshed_then_scheduled(
    client: AsyncClient, session_factory: Factory
) -> None:
    from ai_crm.work.runner import enqueue_scheduled_syncs

    connection = await make_connection(client, "sched-expired")
    await expire(session_factory, connection["id"])

    count = await enqueue_scheduled_syncs(session_factory, "tenant-a", datetime.now(UTC))
    row = await connection_row(session_factory, connection["id"])

    assert count == 1
    assert row.status == "connected"
    assert row.token_expires_at is not None
    assert row.token_expires_at.replace(tzinfo=UTC) > datetime.now(UTC)


async def test_permanent_refresh_failure_flags_connection_and_blocks_sync(
    client: AsyncClient, session_factory: Factory
) -> None:
    from ai_crm.work.runner import enqueue_scheduled_syncs

    connection = await make_connection(
        client, "sched-reauth", configuration={"refresh_failure": "invalid_grant"}
    )
    await expire(session_factory, connection["id"])

    count = await enqueue_scheduled_syncs(session_factory, "tenant-a", datetime.now(UTC))
    row = await connection_row(session_factory, connection["id"])
    sync = await client.post(
        f"/api/v1/integrations/connections/{connection['id']}/sync",
        headers=tenant_headers("tenant-a"),
    )

    assert count == 0
    assert row.status == "needs_reauth" and row.last_error_code == "invalid_grant"
    assert sync.status_code == 422
    assert await jobs_of_type(session_factory, "integration.sync") == []


async def test_transient_refresh_failure_keeps_connection_and_retries_next_interval(
    client: AsyncClient, session_factory: Factory
) -> None:
    from ai_crm.work.runner import enqueue_scheduled_syncs

    connection = await make_connection(
        client, "sched-transient", configuration={"refresh_failure": "rate_limit"}
    )
    await expire(session_factory, connection["id"])

    count = await enqueue_scheduled_syncs(session_factory, "tenant-a", datetime.now(UTC))
    row = await connection_row(session_factory, connection["id"])

    assert count == 0
    assert row.status == "connected" and row.last_error_code == "rate_limit"


async def test_needs_reauth_creates_one_deduplicated_alert_and_work_item(
    client: AsyncClient, session_factory: Factory
) -> None:
    from ai_crm.work.runner import enqueue_scheduled_syncs

    flagged = await make_connection(
        client, "alert-reauth", configuration={"refresh_failure": "invalid_grant"}
    )
    other = await make_connection(
        client, "alert-other-tenant", tenant_id="tenant-b",
        configuration={"refresh_failure": "invalid_grant"},
    )
    for connection in (flagged, other):
        await expire(session_factory, connection["id"])
    await enqueue_scheduled_syncs(session_factory, "tenant-a", datetime.now(UTC))
    await enqueue_scheduled_syncs(session_factory, "tenant-b", datetime.now(UTC))

    first = await client.post(
        "/api/v1/observability/proactive-checks/run", headers=tenant_headers("tenant-a")
    )
    second = await client.post(
        "/api/v1/observability/proactive-checks/run", headers=tenant_headers("tenant-a")
    )
    alerts = await client.get("/api/v1/observability/alerts", headers=tenant_headers("tenant-a"))

    assert first.json()["alerts_created"] == 1 and first.json()["work_items_created"] == 1
    assert second.json()["alerts_created"] == 0 and second.json()["suppressed_duplicates"] == 1
    assert [a["related_id"] for a in alerts.json()] == [flagged["id"]]



async def test_duplicate_webhook_delivery_keeps_processed_state(
    client: AsyncClient, session_factory: Factory
) -> None:
    await make_connection(client, "wh-dup")
    stamp = datetime.now(UTC).isoformat()
    await send_webhook(client, "wh-dup", "evt-dup", timestamp=stamp)
    await run_tick(session_factory)

    replay = await send_webhook(client, "wh-dup", "evt-dup", timestamp=stamp)
    event = await webhook_event(session_factory, "evt-dup")

    assert replay.status_code == 202 and replay.json()["status"] == "duplicate"
    assert event is not None and event.status == "processed"
    assert len(await jobs_of_type(session_factory, "integration.webhook")) == 1


async def test_losing_a_claim_race_falls_through_to_the_next_ready_job(
    client: AsyncClient, session_factory: Factory
) -> None:
    await create_job(client, "notification.send", {}, key="race-1")
    await create_job(client, "notification.send", {}, key="race-2")
    context = RequestContext(
        tenant_id="tenant-a",
        actor_id="system:worker",
        role="system",
        correlation_id="race2",
        permissions=frozenset({Permission.JOBS_MANAGE}),
    )

    async def claim(worker_id: str) -> DurableJob | None:
        async with session_factory() as session:
            return await claim_next_job(
                session, context, queue="default", worker_id=worker_id, lease_seconds=60
            )

    results = await asyncio.gather(claim("w1"), claim("w2"))

    assert all(result is not None for result in results)
    assert len({result.id for result in results if result}) == 2


async def test_each_process_has_a_distinct_lease_owner_id() -> None:
    from ai_crm.work import runner

    assert runner.WORKER_ID.startswith("worker-")
    assert runner.WORKER_ID != runner.ACTOR_ID


async def test_scheduler_continues_after_one_connection_fails(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_crm.work import runner as runner_module

    first = await make_connection(client, "sched-fail-1")
    second = await make_connection(client, "sched-fail-2")
    real = runner_module.create_job

    async def flaky(session, context, payload, key):
        if first["id"] in key:
            raise RuntimeError("boom")
        return await real(session, context, payload, key)

    monkeypatch.setattr(runner_module, "create_job", flaky)

    count = await runner_module.enqueue_scheduled_syncs(
        session_factory, "tenant-a", datetime.now(UTC)
    )
    jobs = await jobs_of_type(session_factory, "integration.sync")

    assert count == 1
    assert [job.payload["connection_id"] for job in jobs] == [second["id"]]


async def test_webhook_for_revoked_or_disconnected_connection_is_rejected(
    client: AsyncClient, session_factory: Factory
) -> None:
    revoked = await make_connection(client, "wh-revoked")
    disconnected = await make_connection(client, "wh-disconnected")
    for connection, action in ((revoked, "revoke"), (disconnected, "disconnect")):
        await client.post(
            f"/api/v1/integrations/connections/{connection['id']}/{action}",
            headers=tenant_headers("tenant-a"),
        )

    first = await send_webhook(client, "wh-revoked", "evt-r")
    second = await send_webhook(client, "wh-disconnected", "evt-d")

    assert first.status_code == 409 and second.status_code == 409
    assert await jobs_of_type(session_factory, "integration.webhook") == []


async def test_scheduler_honours_failed_sync_backoff(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_crm.integrations import sync_connection
    from ai_crm.work.runner import enqueue_scheduled_syncs

    connection = await make_connection(client, "sched-backoff")
    fail_listing(monkeypatch, "rate_limit")
    context = RequestContext(
        tenant_id="tenant-a",
        actor_id="user-d",
        role="admin",
        correlation_id="backoff",
        permissions=frozenset({Permission.INTEGRATIONS_SYNC}),
    )
    async with session_factory() as session:
        run = await sync_connection(session, context, connection["id"], "incremental")
    assert run.status == "failed" and run.next_retry_at is not None

    during = await enqueue_scheduled_syncs(session_factory, "tenant-a", datetime.now(UTC))
    later = await enqueue_scheduled_syncs(
        session_factory, "tenant-a", datetime.now(UTC) + timedelta(hours=2)
    )

    assert (during, later) == (0, 1)


async def test_concurrent_webhook_delivery_never_errors_and_creates_one_job(
    client: AsyncClient, session_factory: Factory
) -> None:
    from ai_crm.integrations import ingest_webhook

    await make_connection(client, "wh-race")
    stamp = datetime.now(UTC).isoformat()

    async def deliver():
        import hashlib
        import hmac
        import json

        body = json.dumps(
            {"id": "evt-race", "type": "activity.updated", "timestamp": stamp},
            separators=(",", ":"),
        ).encode()
        signature = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        async with session_factory() as session:
            return await ingest_webhook(session, "fixture", "wh-race", signature, body)

    results = await asyncio.gather(deliver(), deliver())

    assert sorted(duplicate for _, duplicate in results) == [False, True]
    assert len(await jobs_of_type(session_factory, "integration.webhook")) == 1


async def test_sync_backoff_accumulates_and_permanent_failures_pause_scheduling(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_crm.integrations import sync_connection
    from ai_crm.work.runner import enqueue_scheduled_syncs

    connection = await make_connection(client, "sync-accumulate")
    context = RequestContext(
        tenant_id="tenant-a",
        actor_id="user-d",
        role="admin",
        correlation_id="acc",
        permissions=frozenset({Permission.INTEGRATIONS_SYNC}),
    )

    async def run_once():
        async with session_factory() as session:
            return await sync_connection(session, context, connection["id"], "incremental")

    fail_listing(monkeypatch, "rate_limit")
    first, second = await run_once(), await run_once()
    fail_listing(monkeypatch, "invalid_account")
    permanent = await run_once()
    later = datetime.now(UTC) + timedelta(days=1)
    scheduled = await enqueue_scheduled_syncs(session_factory, "tenant-a", later)

    assert (first.retry_count, second.retry_count) == (1, 2)
    assert first.next_retry_at is not None and second.next_retry_at is not None
    assert second.next_retry_at > first.next_retry_at
    assert permanent.status == "failed" and permanent.next_retry_at is None
    assert scheduled == 0


async def test_run_tick_reports_failed_tenants(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_crm.work import runner as runner_module

    async def broken(session, context):
        raise RuntimeError("db down")

    monkeypatch.setattr(runner_module, "reconcile_expired_jobs", broken)
    failures: list[str] = []

    await run_tick(session_factory, failures=failures)

    assert sorted(failures) == ["tenant-a", "tenant-b"]
