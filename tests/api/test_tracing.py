import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from ai_crm.auth import create_access_token
from ai_crm.main import parse_traceparent
from ai_crm.permissions import Permission
from ai_crm.work import handlers as handlers_module
from ai_crm.work.runner import run_tick

pytestmark = pytest.mark.asyncio

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT = f"00-{TRACE}-00f067aa0ba902b7-01"


def tenant_headers(tenant_id: str = "tenant-a", user_id: str = "user-d") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-ID": tenant_id,
    }


async def events(client: AsyncClient, trace_id: str, tenant_id: str = "tenant-a"):
    response = await client.get(
        "/api/v1/observability/events",
        headers=tenant_headers(tenant_id),
        params={"trace_id": trace_id, "limit": 500},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "garbage",
        f"01-{TRACE}-00f067aa0ba902b7-01",
        f"00-{'0' * 32}-00f067aa0ba902b7-01",
        f"00-{TRACE}-{'0' * 16}-01",
        f"00-{TRACE[:-1]}-00f067aa0ba902b7-01",
    ],
)
async def test_invalid_traceparent_is_ignored(value: str | None) -> None:
    assert parse_traceparent(value) is None


async def test_valid_traceparent_yields_trace_id() -> None:
    assert parse_traceparent(PARENT.upper()) == TRACE


async def test_response_carries_continued_or_fresh_trace(client: AsyncClient) -> None:
    continued = await client.get("/api/v1/health", headers={"traceparent": PARENT})
    fresh = await client.get("/api/v1/health", headers={"traceparent": "bad"})

    _, trace_id, span_id, flags = continued.headers["traceparent"].split("-")
    assert trace_id == TRACE and span_id != "00f067aa0ba902b7" and flags == "01"
    fresh_trace = fresh.headers["traceparent"].split("-")[1]
    assert len(fresh_trace) == 32 and fresh_trace != TRACE
    assert "X-Correlation-ID" in continued.headers


async def test_request_events_are_queryable_by_trace_and_tenant_scoped(
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/api/v1/contacts",
        headers={**tenant_headers(), "traceparent": PARENT},
        json={"first_name": "Trace", "last_name": "Me"},
    )
    found = await events(client, TRACE)
    other_tenant = await events(client, TRACE, "tenant-b")
    bad = await client.get(
        "/api/v1/observability/events",
        headers=tenant_headers(),
        params={"trace_id": "short"},
    )

    assert created.status_code == 201
    assert any(item["event_type"] == "contact.created" for item in found)
    assert all(item["trace_id"] == TRACE for item in found)
    assert other_tenant == []
    assert bad.status_code == 422


async def test_trace_follows_a_request_into_the_worker(
    client: AsyncClient, session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok(session, context, job):
        assert context.trace_id == TRACE
        return {}

    monkeypatch.setitem(
        handlers_module.HANDLERS, "notification.send", (ok, frozenset({Permission.WORK_MANAGE}))
    )
    job = await client.post(
        "/api/v1/jobs",
        headers={**tenant_headers(), "Idempotency-Key": "trace-job", "traceparent": PARENT},
        json={"job_type": "notification.send", "payload": {}},
    )

    await run_tick(session_factory)
    found = await events(client, TRACE)

    assert job.json()["trace_id"] == TRACE
    types = {item["event_type"] for item in found}
    assert {"job.created", "job.claimed", "job.completed"} <= types


async def test_trace_follows_a_webhook_into_its_sync(
    client: AsyncClient, session_factory
) -> None:
    secret = "trace-secret"
    await client.post(
        "/api/v1/integrations/connections",
        headers=tenant_headers(),
        json={
            "provider_key": "fixture",
            "external_account_id": "trace-account",
            "scopes": ["activities:read"],
            "secret_ref": secret,
        },
    )
    body = json.dumps(
        {"id": "trace-evt", "type": "activity.updated", "timestamp": datetime.now(UTC).isoformat()},
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    accepted = await client.post(
        "/api/v1/integrations/webhooks/fixture",
        headers={
            "X-Integration-Account": "trace-account",
            "X-Webhook-Signature": f"sha256={signature}",
            "Content-Type": "application/json",
            "traceparent": PARENT,
        },
        content=body,
    )

    await run_tick(session_factory)
    found = await events(client, TRACE)

    assert accepted.status_code == 202
    types = {item["event_type"] for item in found}
    assert {"integration.webhook.received", "integration.sync.succeeded", "job.completed"} <= types
