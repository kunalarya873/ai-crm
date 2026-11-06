from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from ai_crm.auth import create_access_token

pytestmark = pytest.mark.asyncio


def tenant_headers(tenant_id: str, user_id: str = "user-a") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-ID": tenant_id,
    }


async def test_metrics_events_redaction_and_summary_permissions(client: AsyncClient) -> None:
    headers = tenant_headers("tenant-a")
    contact = await client.post(
        "/api/v1/contacts",
        headers=headers,
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada.private@example.com",
        },
    )
    await client.patch(
        f"/api/v1/contacts/{contact.json()['id']}",
        headers={**headers, "If-Match": '"1"'},
        json={"email": "ada.private@example.com"},
    )
    collected = await client.post(
        "/api/v1/observability/metrics/collect",
        headers=headers,
    )
    metrics = await client.get("/api/v1/observability/metrics", headers=headers)
    events = await client.get("/api/v1/observability/events", headers=headers)
    summary = await client.get("/api/v1/observability/summary", headers=headers)
    viewer_collect = await client.post(
        "/api/v1/observability/metrics/collect",
        headers=tenant_headers("tenant-a", "user-b"),
    )

    assert contact.status_code == 201
    assert collected.status_code == 201, collected.text
    assert {item["metric_key"] for item in collected.json()} >= {
        "events.count",
        "work.overdue",
        "ai.runs",
    }
    assert metrics.status_code == 200
    assert summary.status_code == 200
    assert summary.json()["window_start"] < summary.json()["window_end"]
    assert events.status_code == 200
    contact_events = [
        item for item in events.json() if item["resource_id"] == contact.json()["id"]
    ]
    assert contact_events
    updated_event = next(item for item in contact_events if item["event_type"] == "contact.updated")
    assert updated_event["payload"]["new"]["email"]["redacted"] is True
    assert viewer_collect.status_code == 403


async def test_proactive_checks_create_deduplicated_alert_and_review_work_item(
    client: AsyncClient,
) -> None:
    due_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    created = await client.post(
        "/api/v1/work-items",
        headers=tenant_headers("tenant-a"),
        json={"item_type": "commitment", "title": "Missed commitment", "due_at": due_at},
    )
    first = await client.post(
        "/api/v1/observability/proactive-checks/run",
        headers=tenant_headers("tenant-a"),
    )
    second = await client.post(
        "/api/v1/observability/proactive-checks/run",
        headers=tenant_headers("tenant-a"),
    )
    alerts = await client.get(
        "/api/v1/observability/alerts",
        headers=tenant_headers("tenant-a"),
        params={"status": "open"},
    )
    escalation_items = await client.get(
        "/api/v1/work-items",
        headers=tenant_headers("tenant-a"),
        params={"item_type": "escalation"},
    )

    assert created.status_code == 201
    assert first.status_code == 200
    assert first.json()["alerts_created"] == 1
    assert first.json()["work_items_created"] == 1
    assert second.status_code == 200
    assert second.json()["suppressed_duplicates"] == 1
    assert alerts.status_code == 200
    assert len(alerts.json()) == 1
    assert escalation_items.status_code == 200
    assert len(escalation_items.json()) == 1
    assert escalation_items.json()[0]["status"] == "open"


async def test_alert_acknowledge_and_resolve_and_tenant_isolation(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/work-items",
        headers=tenant_headers("tenant-a"),
        json={
            "title": "Another overdue item",
            "due_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        },
    )
    run = await client.post(
        "/api/v1/observability/proactive-checks/run",
        headers=tenant_headers("tenant-a"),
    )
    alert_id = run.json()["alert_ids"][0]
    acknowledged = await client.post(
        f"/api/v1/observability/alerts/{alert_id}/acknowledge",
        headers=tenant_headers("tenant-a"),
        json={"note": "Owner notified"},
    )
    resolved = await client.post(
        f"/api/v1/observability/alerts/{alert_id}/resolve",
        headers=tenant_headers("tenant-a"),
        json={"note": "Commitment rescheduled"},
    )
    other_tenant = await client.get(
        f"/api/v1/observability/alerts/{alert_id}",
        headers=tenant_headers("tenant-b"),
    )

    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "acknowledged"
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolution_note"] == "Commitment rescheduled"
    assert other_tenant.status_code == 404
