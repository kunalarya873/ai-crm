from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from ai_crm.auth import create_access_token
from ai_crm.models import AuditEvent, OutboxEvent

pytestmark = pytest.mark.asyncio


def tenant_headers(tenant_id: str, user_id: str = "user-a") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-ID": tenant_id,
    }


async def test_health_does_not_require_tenant(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness_reports_database_health(client: AsyncClient) -> None:
    response = await client.get("/api/v1/readiness")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


async def test_tenant_header_is_required_for_crm_routes(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/contacts",
        headers={"Authorization": f"Bearer {create_access_token('user-a')}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "X-Tenant-ID header is required"


async def test_contact_creation_and_tenant_isolation(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/contacts",
        headers=tenant_headers("tenant-a", "user-a"),
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "company_name": "Analytical Engines",
        },
    )

    assert response.status_code == 201
    contact = response.json()
    assert contact["tenant_id"] == "tenant-a"
    assert contact["first_name"] == "Ada"

    same_tenant = await client.get(
        "/api/v1/contacts",
        headers=tenant_headers("tenant-a"),
    )
    other_tenant = await client.get(
        "/api/v1/contacts",
        headers=tenant_headers("tenant-b"),
    )

    assert same_tenant.status_code == 200
    assert len(same_tenant.json()) == 1
    assert other_tenant.status_code == 200
    assert other_tenant.json() == []

    hidden_contact = await client.get(
        f"/api/v1/contacts/{contact['id']}",
        headers=tenant_headers("tenant-b"),
    )
    assert hidden_contact.status_code == 404


async def test_contact_creation_records_audit_and_outbox_events(
    client: AsyncClient,
    session_factory,
) -> None:
    correlation_id = "123e4567-e89b-12d3-a456-426614174000"
    response = await client.post(
        "/api/v1/contacts",
        headers={
            **tenant_headers("tenant-a"),
            "X-Correlation-ID": correlation_id,
        },
        json={"first_name": "Event", "last_name": "Test"},
    )
    contact_id = response.json()["id"]

    async with session_factory() as session:
        audit_event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_id == contact_id,
                AuditEvent.action == "contact.created",
            )
        )
        outbox_event = await session.scalar(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == contact_id)
        )

    assert response.status_code == 201
    assert audit_event is not None
    assert audit_event.correlation_id == correlation_id
    assert audit_event.actor_id == "user-a"
    assert outbox_event is not None
    assert outbox_event.event_type == "contact.created"
    assert outbox_event.correlation_id == correlation_id


async def test_task_requires_a_contact_in_the_same_tenant(client: AsyncClient) -> None:
    contact_response = await client.post(
        "/api/v1/contacts",
        headers=tenant_headers("tenant-a"),
        json={"first_name": "Grace", "last_name": "Hopper"},
    )
    contact_id = contact_response.json()["id"]

    task_response = await client.post(
        "/api/v1/tasks",
        headers=tenant_headers("tenant-a"),
        json={"title": "Schedule follow-up", "contact_id": contact_id},
    )
    assert task_response.status_code == 201
    assert task_response.json()["contact_id"] == contact_id

    cross_tenant_task = await client.post(
        "/api/v1/tasks",
        headers=tenant_headers("tenant-b"),
        json={"title": "Attempted cross-tenant link", "contact_id": contact_id},
    )
    assert cross_tenant_task.status_code == 404


async def test_contact_validation_rejects_blank_names(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/contacts",
        headers=tenant_headers("tenant-a"),
        json={"first_name": " ", "last_name": "Valid"},
    )

    assert response.status_code == 422


async def test_unexpected_fields_are_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/contacts",
        headers=tenant_headers("tenant-a"),
        json={"first_name": "Strict", "last_name": "Input", "is_admin": True},
    )

    assert response.status_code == 422


async def test_missing_bearer_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/contacts", headers={"X-Tenant-ID": "tenant-a"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_request_headers_cannot_impersonate_user_or_role(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/contacts",
        headers={
            **tenant_headers("tenant-a", "user-b"),
            "X-User-ID": "user-a",
            "X-User-Role": "admin",
        },
        json={"first_name": "Viewer", "last_name": "User"},
    )

    assert response.status_code == 403


async def test_viewer_can_read_but_cannot_create(client: AsyncClient) -> None:
    headers = tenant_headers("tenant-a", "user-b")

    read_response = await client.get("/api/v1/contacts", headers=headers)
    create_response = await client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"first_name": "Not", "last_name": "Allowed"},
    )

    assert read_response.status_code == 200
    assert create_response.status_code == 403


async def test_unaffiliated_user_is_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/contacts",
        headers=tenant_headers("tenant-a", "unknown-user"),
    )

    assert response.status_code == 401


async def test_correlation_id_is_returned_and_rejects_invalid_values(client: AsyncClient) -> None:
    correlation_id = "123e4567-e89b-12d3-a456-426614174000"
    response = await client.get(
        "/api/v1/contacts",
        headers={**tenant_headers("tenant-a"), "X-Correlation-ID": correlation_id},
    )
    invalid_response = await client.get(
        "/api/v1/contacts",
        headers={**tenant_headers("tenant-a"), "X-Correlation-ID": "not-a-uuid"},
    )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == correlation_id
    assert invalid_response.status_code == 400


async def test_phase2_customer_opportunity_activity_task_workflow(client: AsyncClient) -> None:
    headers = tenant_headers("tenant-a")
    company_response = await client.post(
        "/api/v1/companies",
        headers=headers,
        json={"name": "Acme Corp"},
    )
    company = company_response.json()

    contact_response = await client.post(
        "/api/v1/contacts",
        headers=headers,
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "company_id": company["id"],
        },
    )
    contact = contact_response.json()

    opportunity_response = await client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={
            "name": "CRM Platform",
            "company_id": company["id"],
            "contact_id": contact["id"],
        },
    )
    opportunity = opportunity_response.json()

    activity_response = await client.post(
        "/api/v1/activities",
        headers=headers,
        json={
            "kind": "meeting",
            "subject": "Discovery call",
            "body": "Discussed the initial workflow.",
            "event_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "contact_id": contact["id"],
            "opportunity_id": opportunity["id"],
        },
    )
    task_response = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Send proposal",
            "contact_id": contact["id"],
            "opportunity_id": opportunity["id"],
            "due_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        },
    )

    timeline_response = await client.get(
        f"/api/v1/contacts/{contact['id']}/timeline",
        headers=headers,
    )

    assert company_response.status_code == 201
    assert company_response.headers["ETag"] == '"1"'
    assert contact_response.status_code == 201
    assert contact["company_id"] == company["id"]
    assert opportunity_response.status_code == 201
    assert activity_response.status_code == 201
    assert task_response.status_code == 201
    assert {entry["type"] for entry in timeline_response.json()} == {"activity", "task"}


async def test_phase2_optimistic_concurrency_and_transitions(client: AsyncClient) -> None:
    headers = tenant_headers("tenant-a")
    company_response = await client.post(
        "/api/v1/companies",
        headers=headers,
        json={"name": "Versioned Company"},
    )
    company = company_response.json()

    missing_precondition = await client.patch(
        f"/api/v1/companies/{company['id']}",
        headers=headers,
        json={"status": "customer"},
    )
    first_update = await client.patch(
        f"/api/v1/companies/{company['id']}",
        headers={**headers, "If-Match": '"1"'},
        json={"status": "customer"},
    )
    stale_update = await client.patch(
        f"/api/v1/companies/{company['id']}",
        headers={**headers, "If-Match": '"1"'},
        json={"name": "Stale Update"},
    )

    assert missing_precondition.status_code == 428
    assert first_update.status_code == 200
    assert first_update.headers["ETag"] == '"2"'
    assert first_update.json()["version"] == 2
    assert stale_update.status_code == 409
    assert stale_update.json()["code"] == "record_version_conflict"

    contact_response = await client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"first_name": "Transition", "last_name": "Test"},
    )
    contact = contact_response.json()
    transition_response = await client.patch(
        f"/api/v1/contacts/{contact['id']}",
        headers={**headers, "If-Match": '"1"'},
        json={"status": "customer"},
    )

    assert transition_response.status_code == 409
    assert transition_response.json()["code"] == "invalid_transition"


async def test_phase2_duplicate_company_and_activity_are_rejected(client: AsyncClient) -> None:
    headers = tenant_headers("tenant-a")
    first_company = await client.post(
        "/api/v1/companies",
        headers=headers,
        json={"name": "Duplicate Name"},
    )
    duplicate_company = await client.post(
        "/api/v1/companies",
        headers=headers,
        json={"name": "  duplicate   name "},
    )
    contact = await client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"first_name": "Source", "last_name": "Record"},
    )
    source_payload = {
        "kind": "email",
        "subject": "Imported email",
        "contact_id": contact.json()["id"],
        "source_system": "mail",
        "source_record_id": "message-1",
    }
    first_activity = await client.post("/api/v1/activities", headers=headers, json=source_payload)
    duplicate_activity = await client.post(
        "/api/v1/activities",
        headers=headers,
        json=source_payload,
    )

    assert first_company.status_code == 201
    assert duplicate_company.status_code == 409
    assert first_activity.status_code == 201
    assert duplicate_activity.status_code == 409
