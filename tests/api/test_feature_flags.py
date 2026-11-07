import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_crm.config import Settings, settings
from ai_crm.models import AuditEvent, DurableJob
from ai_crm.work.runner import run_tick
from tests.api.agent_helpers import API, act, headers, make_agent, start, start_raw, step

Factory = async_sessionmaker[AsyncSession]
ADMIN = "user-d"
FLAGS = ["ai", "workflows", "connectors", "agents"]


async def put_flag(
    client: AsyncClient,
    flag: str,
    enabled: bool,
    *,
    reason: str | None = "incident INC-1",
    version: object = 0,
    user: str = ADMIN,
    tenant: str = "tenant-a",
) -> Response:
    body: dict[str, Any] = {"enabled": enabled}
    if reason is not None:
        body["reason"] = reason
    return await client.put(
        f"{API}/admin/feature-flags/{flag}",
        headers={**headers(user, tenant), "If-Match": f'"{version}"'},
        json=body,
    )


async def flags(client: AsyncClient, tenant: str = "tenant-a") -> dict[str, dict[str, Any]]:
    response = await client.get(f"{API}/admin/feature-flags", headers=headers(ADMIN, tenant))
    assert response.status_code == 200
    return {item["flag"]: item for item in response.json()}


async def audit_actions(factory: Factory) -> list[str]:
    async with factory() as session:
        return [e.action for e in await session.scalars(select(AuditEvent))]


async def test_flags_default_to_enabled_and_toggle_with_reason_and_version(
    client: AsyncClient, session_factory: Factory
) -> None:
    initial = await flags(client)
    disabled = await put_flag(client, "ai", False)
    enabled = await put_flag(client, "ai", True, reason=None, version=1)
    actions = await audit_actions(session_factory)

    assert list(initial) == FLAGS
    assert all(
        f["enabled"] and f["version"] == 0 and f["source"] == "default"
        for f in initial.values()
    )
    assert disabled.status_code == 200 and disabled.json()["enabled"] is False
    assert disabled.json()["source"] == "tenant" and disabled.json()["reason"] == "incident INC-1"
    assert disabled.headers["etag"] == '"1"'
    assert enabled.json()["enabled"] is True and enabled.json()["version"] == 2
    assert "capability.disabled" in actions and "capability.enabled" in actions


async def test_flag_write_validation(client: AsyncClient) -> None:
    no_reason = await put_flag(client, "ai", False, reason=None)
    unknown = await put_flag(client, "payments", False)
    no_header = await client.put(
        f"{API}/admin/feature-flags/ai",
        headers=headers(ADMIN),
        json={"enabled": False, "reason": "x"},
    )
    await put_flag(client, "ai", False)
    stale = await put_flag(client, "ai", True, reason=None, version=0)

    assert no_reason.status_code == 422
    assert unknown.status_code == 404
    assert no_header.status_code == 428
    assert stale.status_code == 409


async def test_flag_permissions(client: AsyncClient) -> None:
    manager_read = await client.get(f"{API}/admin/feature-flags", headers=headers("user-c"))
    manager_write = await put_flag(client, "ai", False, user="user-c")
    member_read = await client.get(f"{API}/admin/feature-flags", headers=headers("user-a"))
    viewer_write = await put_flag(client, "ai", False, user="user-b")

    assert manager_read.status_code == 200
    assert manager_write.status_code == 403
    assert member_read.status_code == 403
    assert viewer_write.status_code == 403


async def ai_call(client: AsyncClient, key: str = "k") -> Response:
    return await client.post(
        f"{API}/ai/customer-summary",
        headers={**headers("user-a"), "Idempotency-Key": key},
        json={"query": "renewal", "customer_id": "acme"},
    )


async def workflow_start(client: AsyncClient, key: str = "w1") -> Response:
    return await client.post(
        f"{API}/workflows",
        headers={**headers("user-a"), "Idempotency-Key": key},
        json={"workflow_key": "customer_follow_up", "input_refs": {"contact_id": "c1"}},
    )


async def connection(client: AsyncClient, account: str = "acct-1") -> dict[str, Any]:
    response = await client.post(
        f"{API}/integrations/connections",
        headers=headers(ADMIN),
        json={
            "provider_key": "fixture",
            "external_account_id": account,
            "scopes": ["activities:read", "activities:write"],
            "secret_ref": "webhook-secret",
        },
    )
    assert response.status_code == 201
    return response.json()


def webhook(account: str, event_id: str) -> tuple[dict[str, str], bytes]:
    body = json.dumps(
        {
            "id": event_id,
            "type": "activity.created",
            "timestamp": datetime.now(UTC).isoformat(),
            "data": {"subject": "x"},
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
    return {
        "X-Integration-Account": account,
        "X-Webhook-Signature": f"sha256={signature}",
        "Content-Type": "application/json",
    }, body


async def test_ai_switch_blocks_generation_but_not_reads(
    client: AsyncClient, session_factory: Factory
) -> None:
    ok = await ai_call(client, "a")
    await put_flag(client, "ai", False)
    blocked = await ai_call(client, "b")
    read = await client.get(f"{API}/ai/runs", headers=headers("user-a"))
    health = await client.get(f"{API}/ai/providers/health", headers=headers("user-a"))
    await put_flag(client, "ai", True, reason=None, version=1)
    restored = await ai_call(client, "c")

    assert ok.status_code == 200
    assert blocked.status_code == 503 and blocked.json()["code"] == "capability_disabled"
    assert read.status_code == 200 and health.status_code == 200
    assert restored.status_code == 200
    assert "capability.blocked" in await audit_actions(session_factory)


async def test_workflow_switch(client: AsyncClient) -> None:
    started = await workflow_start(client, "w1")
    await put_flag(client, "workflows", False)
    blocked_start = await workflow_start(client, "w2")
    blocked_advance = await client.post(
        f"{API}/workflows/{started.json()['id']}/advance",
        headers={**headers("user-a"), "If-Match": '"1"'},
        json={"output": {}},
    )
    read = await client.get(f"{API}/workflows/{started.json()['id']}", headers=headers("user-a"))

    assert blocked_start.status_code == 503
    assert blocked_advance.status_code == 503
    assert read.status_code == 200


async def test_connector_switch_blocks_sync_write_test_refresh_and_webhook(
    client: AsyncClient,
) -> None:
    conn = await connection(client)
    url = f"{API}/integrations/connections/{conn['id']}"
    await put_flag(client, "connectors", False)
    webhook_headers, body = webhook("acct-1", "evt-1")

    sync = await client.post(f"{url}/sync", headers=headers(ADMIN))
    test = await client.post(f"{url}/test", headers=headers(ADMIN))
    refresh = await client.post(f"{url}/refresh", headers=headers(ADMIN))
    write = await client.post(
        f"{url}/writes",
        headers={**headers(ADMIN), "Idempotency-Key": "w"},
        json={"operation": "activity.create", "payload": {"subject": "s"}},
    )
    hook = await client.post(
        f"{API}/integrations/webhooks/fixture", headers=webhook_headers, content=body
    )
    read = await client.get(f"{API}/integrations/connections", headers=headers(ADMIN))
    await put_flag(client, "connectors", True, reason=None, version=1)
    restored = await client.post(f"{url}/sync", headers=headers(ADMIN))
    hook_ok = await client.post(
        f"{API}/integrations/webhooks/fixture", headers=webhook_headers, content=body
    )

    for response in (sync, test, refresh, write, hook):
        assert response.status_code == 503, response.text
        assert response.json()["code"] == "capability_disabled"
    assert read.status_code == 200
    assert restored.status_code == 200
    assert hook_ok.status_code == 202


async def test_connection_can_still_be_disconnected_while_connectors_are_off(
    client: AsyncClient,
) -> None:
    conn = await connection(client)
    await put_flag(client, "connectors", False)

    response = await client.post(
        f"{API}/integrations/connections/{conn['id']}/disconnect", headers=headers(ADMIN)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"


async def test_agent_switch_blocks_new_work_but_allows_wind_down(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    running = await start(client, agent, objective="running")
    paused = await start(client, agent, objective="paused")
    await act(client, paused, "pause")
    await put_flag(client, "agents", False)

    new_run = await start_raw(client, agent, objective="new", key="n1")
    new_step = await step(client, running["id"], "s", "output", {"summary": "x"})
    resume = await act(client, paused, "resume")
    cancel = await act(client, paused, "cancel")
    pause = await act(client, running, "pause")
    read = await client.get(f"{API}/agent-runs/{running['id']}", headers=headers())
    evaluation = await client.post(
        f"{API}/agent-evals/run", headers=headers(ADMIN), json={"replay_key": "r"}
    )

    assert new_run.status_code == new_step.status_code == resume.status_code == 503
    assert evaluation.status_code == 503
    assert cancel.status_code == 200 and pause.status_code == 200 and read.status_code == 200


async def test_flags_are_tenant_isolated(client: AsyncClient) -> None:
    await put_flag(client, "ai", False, tenant="tenant-a")

    a = await flags(client, "tenant-a")
    b = await flags(client, "tenant-b")
    other = await client.post(
        f"{API}/ai/customer-summary",
        headers={**headers("user-a", "tenant-b"), "Idempotency-Key": "b"},
        json={"query": "x"},
    )

    assert a["ai"]["enabled"] is False
    assert b["ai"]["enabled"] is True and b["ai"]["source"] == "default"
    assert other.status_code == 200


async def test_platform_switch_overrides_tenant_state(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await put_flag(client, "workflows", True, reason=None, version=0)  # explicit enable row
    monkeypatch.setattr(settings, "disabled_capabilities", "ai, workflows")

    listing = await flags(client)
    ai = await ai_call(client, "p")
    wf = await workflow_start(client, "p")

    assert listing["ai"]["source"] == listing["workflows"]["source"] == "platform"
    assert listing["ai"]["enabled"] is False and listing["connectors"]["enabled"] is True
    assert ai.status_code == wf.status_code == 503


def test_invalid_platform_switch_names_are_rejected_at_load() -> None:
    with pytest.raises(ValueError, match="Unknown DISABLED_CAPABILITIES"):
        Settings(debug=True, disabled_capabilities="ai,payments")
    assert Settings(debug=True, disabled_capabilities=" ai , agents ").disabled_capability_set == {
        "ai",
        "agents",
    }


async def test_worker_leaves_connector_jobs_queued_while_disabled(
    client: AsyncClient, session_factory: Factory
) -> None:
    conn = await connection(client)

    async def make_job(job_type: str, payload: dict[str, Any], key: str) -> str:
        response = await client.post(
            f"{API}/jobs",
            headers={**headers("user-a"), "Idempotency-Key": key},
            json={"job_type": job_type, "payload": payload, "backoff_seconds": 0},
        )
        assert response.status_code == 201
        return response.json()["id"]

    sync_id = await make_job(
        "integration.sync", {"connection_id": conn["id"], "mode": "initial"}, "j1"
    )
    await put_flag(client, "connectors", False)

    await run_tick(session_factory)
    async with session_factory() as session:
        queued = await session.get_one(DurableJob, sync_id)
    await put_flag(client, "connectors", True, reason=None, version=1)
    await run_tick(session_factory)
    async with session_factory() as session:
        done = await session.get_one(DurableJob, sync_id)

    assert queued.status == "queued" and queued.attempts == 0
    assert done.status == "succeeded"


async def test_job_claimed_before_the_switch_flipped_is_retried_not_dead_lettered(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = await connection(client)
    response = await client.post(
        f"{API}/jobs",
        headers={**headers("user-a"), "Idempotency-Key": "inflight"},
        json={
            "job_type": "integration.sync",
            "payload": {"connection_id": conn["id"], "mode": "initial"},
            "backoff_seconds": 0,
            "max_attempts": 3,
        },
    )
    job_id = response.json()["id"]
    # Simulate the switch flipping after the claim: the claim filter still lets it through.
    monkeypatch.setattr("ai_crm.work.runner.disabled_flags", _none_disabled)
    monkeypatch.setattr(settings, "worker_batch_size", 1)  # zero backoff would re-claim
    await put_flag(client, "connectors", False)

    await run_tick(session_factory)
    async with session_factory() as session:
        job = await session.get_one(DurableJob, job_id)

    assert job.status == "retryable" and job.error_code == "CapabilityDisabledError"


async def _none_disabled(session: AsyncSession, tenant_id: str) -> frozenset[str]:
    return frozenset()
