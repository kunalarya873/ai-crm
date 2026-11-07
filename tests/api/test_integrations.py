import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from ai_crm.auth import create_access_token

pytestmark = pytest.mark.asyncio


def tenant_headers(tenant_id: str, user_id: str = "user-a") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-ID": tenant_id,
    }


async def create_fixture_connection(
    client: AsyncClient,
    *,
    account_id: str = "fixture-account-1",
    secret_ref: str = "fixture-secret",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/integrations/connections",
        headers=tenant_headers("tenant-a", "user-d"),
        json={
            "provider_key": "fixture",
            "external_account_id": account_id,
            "scopes": ["activities:read", "activities:write"],
            "secret_ref": secret_ref,
        },
    )
    assert response.status_code == 201
    return response.json()


async def test_fixture_connection_sync_is_idempotent(client: AsyncClient) -> None:
    connection = await create_fixture_connection(client)
    headers = tenant_headers("tenant-a", "user-d")

    first_sync = await client.post(
        f"/api/v1/integrations/connections/{connection['id']}/sync?mode=initial",
        headers=headers,
    )
    second_sync = await client.post(
        f"/api/v1/integrations/connections/{connection['id']}/sync",
        headers=headers,
    )
    links = await client.get(
        f"/api/v1/integrations/connections/{connection['id']}/links",
        headers=headers,
    )
    runs = await client.get(
        f"/api/v1/integrations/connections/{connection['id']}/sync-runs",
        headers=headers,
    )

    assert first_sync.status_code == 200
    assert first_sync.json()["status"] == "succeeded"
    assert first_sync.json()["records_processed"] == 1
    assert second_sync.status_code == 200
    assert second_sync.json()["records_processed"] == 0
    assert len(links.json()) == 1
    assert len(runs.json()) == 2


async def test_external_write_requires_idempotency_and_connection_state(
    client: AsyncClient,
) -> None:
    connection = await create_fixture_connection(client, account_id="fixture-write-account")
    headers = tenant_headers("tenant-a", "user-d")
    payload = {"operation": "activity.create", "payload": {"subject": "Hello"}}

    first = await client.post(
        f"/api/v1/integrations/connections/{connection['id']}/writes",
        headers={**headers, "Idempotency-Key": "write-1"},
        json=payload,
    )
    replay = await client.post(
        f"/api/v1/integrations/connections/{connection['id']}/writes",
        headers={**headers, "Idempotency-Key": "write-1"},
        json=payload,
    )
    conflicting_replay = await client.post(
        f"/api/v1/integrations/connections/{connection['id']}/writes",
        headers={**headers, "Idempotency-Key": "write-1"},
        json={"operation": "activity.create", "payload": {"subject": "Different"}},
    )
    missing_key = await client.post(
        f"/api/v1/integrations/connections/{connection['id']}/writes",
        headers=headers,
        json=payload,
    )
    await client.post(
        f"/api/v1/integrations/connections/{connection['id']}/disconnect",
        headers=headers,
    )
    disconnected = await client.post(
        f"/api/v1/integrations/connections/{connection['id']}/writes",
        headers={**headers, "Idempotency-Key": "write-2"},
        json=payload,
    )

    assert first.status_code == 200
    assert first.json()["status"] == "succeeded"
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert conflicting_replay.status_code == 409
    assert missing_key.status_code == 422
    assert disconnected.status_code == 422


async def test_webhook_signature_and_replay_protection(client: AsyncClient) -> None:
    secret = "webhook-secret"
    connection = await create_fixture_connection(
        client,
        account_id="fixture-webhook-account",
        secret_ref=secret,
    )
    payload = {
        "id": "webhook-1",
        "type": "activity.created",
        "timestamp": datetime.now(UTC).isoformat(),
        "data": {"subject": "Webhook activity"},
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    webhook_headers = {
        "X-Integration-Account": "fixture-webhook-account",
        "X-Webhook-Signature": f"sha256={signature}",
        "Content-Type": "application/json",
    }

    accepted = await client.post(
        "/api/v1/integrations/webhooks/fixture",
        headers=webhook_headers,
        content=raw_body,
    )
    replay = await client.post(
        "/api/v1/integrations/webhooks/fixture",
        headers=webhook_headers,
        content=raw_body,
    )
    invalid_signature = await client.post(
        "/api/v1/integrations/webhooks/fixture",
        headers={**webhook_headers, "X-Webhook-Signature": "sha256=invalid"},
        content=raw_body,
    )

    assert accepted.status_code == 202
    assert accepted.json()["status"] == "queued"
    assert replay.status_code == 202
    assert replay.json()["status"] == "duplicate"
    assert invalid_signature.status_code == 401
    assert connection["provider_key"] == "fixture"


async def test_integration_permissions_and_tenant_isolation(client: AsyncClient) -> None:
    viewer_response = await client.get(
        "/api/v1/integrations/connections",
        headers=tenant_headers("tenant-a", "user-b"),
    )
    create_response = await client.post(
        "/api/v1/integrations/connections",
        headers=tenant_headers("tenant-a", "user-b"),
        json={
            "provider_key": "fixture",
            "external_account_id": "viewer-account",
            "secret_ref": "secret",
        },
    )
    connection = await create_fixture_connection(client, account_id="tenant-a-account")
    other_tenant = await client.get(
        "/api/v1/integrations/connections",
        headers=tenant_headers("tenant-b", "user-d"),
    )

    assert viewer_response.status_code == 200
    assert create_response.status_code == 403
    assert other_tenant.status_code == 200
    assert all(item["id"] != connection["id"] for item in other_tenant.json())


async def test_revoked_connection_is_terminal_and_disconnected_can_be_retested(
    client: AsyncClient,
) -> None:
    admin = tenant_headers("tenant-a", "user-d")
    revoked = await create_fixture_connection(client, account_id="revoke-account")
    disconnected = await create_fixture_connection(client, account_id="disconnect-account")
    base = "/api/v1/integrations/connections"

    await client.post(f"{base}/{revoked['id']}/revoke", headers=admin)
    await client.post(f"{base}/{disconnected['id']}/disconnect", headers=admin)
    revoked_test = await client.post(f"{base}/{revoked['id']}/test", headers=admin)
    revoked_refresh = await client.post(f"{base}/{revoked['id']}/refresh", headers=admin)
    disconnected_refresh = await client.post(f"{base}/{disconnected['id']}/refresh", headers=admin)
    disconnected_test = await client.post(f"{base}/{disconnected['id']}/test", headers=admin)

    assert revoked_test.status_code == 409
    assert revoked_refresh.status_code == 409
    assert disconnected_refresh.status_code == 409
    assert disconnected_test.status_code == 200
    assert disconnected_test.json()["status"] == "connected"


async def test_refresh_updates_expiry_and_records_failures(client: AsyncClient) -> None:
    admin = tenant_headers("tenant-a", "user-d")
    healthy = await create_fixture_connection(client, account_id="refresh-ok")
    failing = await client.post(
        "/api/v1/integrations/connections",
        headers=admin,
        json={
            "provider_key": "fixture",
            "external_account_id": "refresh-bad",
            "scopes": ["activities:read"],
            "secret_ref": "fixture-secret",
            "configuration": {"refresh_failure": "invalid_grant"},
        },
    )
    base = "/api/v1/integrations/connections"

    ok = await client.post(f"{base}/{healthy['id']}/refresh", headers=admin)
    bad = await client.post(f"{base}/{failing.json()['id']}/refresh", headers=admin)
    listed = await client.get(base, headers=admin)

    assert ok.status_code == 200
    assert ok.json()["token_expires_at"] is not None
    assert ok.json()["last_error_code"] is None
    assert bad.status_code == 422
    failed = next(item for item in listed.json() if item["id"] == failing.json()["id"])
    assert failed["last_error_code"] == "invalid_grant"


async def test_refresh_requires_manage_permission_and_respects_tenant(
    client: AsyncClient,
) -> None:
    connection = await create_fixture_connection(client, account_id="refresh-perm")
    url = f"/api/v1/integrations/connections/{connection['id']}/refresh"

    member = await client.post(url, headers=tenant_headers("tenant-a", "user-a"))
    manager = await client.post(url, headers=tenant_headers("tenant-a", "user-c"))
    other_tenant = await client.post(url, headers=tenant_headers("tenant-b", "user-d"))

    assert member.status_code == 403
    assert manager.status_code == 403
    assert other_tenant.status_code == 404


async def test_permanent_refresh_failure_pauses_connection_until_retested(
    client: AsyncClient,
) -> None:
    admin = tenant_headers("tenant-a", "user-d")
    created = await client.post(
        "/api/v1/integrations/connections",
        headers=admin,
        json={
            "provider_key": "fixture",
            "external_account_id": "reauth-restore",
            "scopes": ["activities:read"],
            "secret_ref": "fixture-secret",
            "configuration": {"refresh_failure": "invalid_grant"},
        },
    )
    url = f"/api/v1/integrations/connections/{created.json()['id']}"

    failed = await client.post(f"{url}/refresh", headers=admin)
    flagged = (await client.get("/api/v1/integrations/connections", headers=admin)).json()[0]
    blocked_sync = await client.post(f"{url}/sync", headers=admin)

    retested = await client.post(f"{url}/test", headers=admin)
    resumed_sync = await client.post(f"{url}/sync", headers=admin)

    assert failed.status_code == 422
    assert flagged["status"] == "needs_reauth"
    assert blocked_sync.status_code == 422
    assert retested.json()["status"] == "connected"
    assert resumed_sync.status_code == 200


async def test_webhook_event_id_longer_than_the_storage_limit_is_rejected(
    client: AsyncClient,
) -> None:
    secret = "webhook-secret"
    await create_fixture_connection(client, account_id="long-id-account", secret_ref=secret)
    raw_body = json.dumps(
        {
            "id": "e" * 101,
            "type": "activity.created",
            "timestamp": datetime.now(UTC).isoformat(),
            "data": {},
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()

    response = await client.post(
        "/api/v1/integrations/webhooks/fixture",
        headers={
            "X-Integration-Account": "long-id-account",
            "X-Webhook-Signature": f"sha256={signature}",
            "Content-Type": "application/json",
        },
        content=raw_body,
    )

    assert response.status_code == 422
