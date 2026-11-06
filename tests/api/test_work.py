from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_crm.auth import create_access_token
from ai_crm.models import DurableJob

pytestmark = pytest.mark.asyncio


def tenant_headers(tenant_id: str, user_id: str = "user-a") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-ID": tenant_id,
    }


async def create_work_item(
    client: AsyncClient,
    payload: dict[str, object] | None = None,
    *,
    tenant_id: str = "tenant-a",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/work-items",
        headers=tenant_headers(tenant_id),
        json={"title": "Follow up with customer", **(payload or {})},
    )
    assert response.status_code == 201
    return response.json()


async def test_work_item_dependencies_transitions_and_due_filters(client: AsyncClient) -> None:
    prerequisite = await create_work_item(client, {"title": "Prepare pricing"})
    dependent = await create_work_item(
        client,
        {
            "title": "Send pricing",
            "item_type": "commitment",
            "depends_on_ids": [prerequisite["id"]],
            "due_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        },
    )
    blocked_by_dependency = await client.post(
        f"/api/v1/work-items/{dependent['id']}/transition",
        headers={**tenant_headers("tenant-a"), "If-Match": '"1"'},
        json={"to_status": "in_progress"},
    )
    prerequisite_started = await client.post(
        f"/api/v1/work-items/{prerequisite['id']}/transition",
        headers={**tenant_headers("tenant-a"), "If-Match": '"1"'},
        json={"to_status": "in_progress"},
    )
    prerequisite_completed = await client.post(
        f"/api/v1/work-items/{prerequisite['id']}/transition",
        headers={**tenant_headers("tenant-a"), "If-Match": '"2"'},
        json={"to_status": "completed", "evidence": "Pricing approved by finance"},
    )
    started = await client.post(
        f"/api/v1/work-items/{dependent['id']}/transition",
        headers={**tenant_headers("tenant-a"), "If-Match": '"1"'},
        json={"to_status": "in_progress"},
    )
    missing_evidence = await client.post(
        f"/api/v1/work-items/{dependent['id']}/transition",
        headers={**tenant_headers("tenant-a"), "If-Match": '"2"'},
        json={"to_status": "completed"},
    )
    completed = await client.post(
        f"/api/v1/work-items/{dependent['id']}/transition",
        headers={**tenant_headers("tenant-a"), "If-Match": '"2"'},
        json={"to_status": "completed", "evidence": "Pricing sent"},
    )
    overdue = await client.get(
        "/api/v1/work-items",
        headers=tenant_headers("tenant-a"),
        params={"overdue": True},
    )

    assert blocked_by_dependency.status_code == 409
    assert prerequisite_started.status_code == 200
    assert prerequisite_completed.status_code == 200
    assert started.status_code == 200
    assert missing_evidence.status_code == 422
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completion_evidence"] == "Pricing sent"
    assert any(item["id"] == dependent["id"] for item in overdue.json()) is False


async def test_work_item_permissions_and_tenant_isolation(client: AsyncClient) -> None:
    item = await create_work_item(client)
    viewer_create = await client.post(
        "/api/v1/work-items",
        headers=tenant_headers("tenant-a", "user-b"),
        json={"title": "Viewer cannot create"},
    )
    viewer_list = await client.get(
        "/api/v1/work-items",
        headers=tenant_headers("tenant-a", "user-b"),
    )
    other_tenant = await client.get(
        f"/api/v1/work-items/{item['id']}",
        headers=tenant_headers("tenant-b"),
    )

    assert viewer_create.status_code == 403
    assert viewer_list.status_code == 200
    assert len(viewer_list.json()) == 1
    assert other_tenant.status_code == 404


async def test_reminder_deduplication_and_acknowledgement(client: AsyncClient) -> None:
    item = await create_work_item(client, {"item_type": "reminder"})
    headers = {**tenant_headers("tenant-a"), "Idempotency-Key": "reminder-1"}
    payload = {
        "reminder_kind": "due_soon",
        "scheduled_for": datetime.now(UTC).isoformat(),
        "timezone": "America/New_York",
    }
    first = await client.post(
        f"/api/v1/work-items/{item['id']}/reminders",
        headers=headers,
        json=payload,
    )
    replay = await client.post(
        f"/api/v1/work-items/{item['id']}/reminders",
        headers=headers,
        json=payload,
    )
    reminders = await client.get(
        f"/api/v1/work-items/{item['id']}/reminders",
        headers=tenant_headers("tenant-a"),
    )
    claimed = await client.post(
        "/api/v1/jobs/claim-next?queue=reminders",
        headers=tenant_headers("tenant-a"),
        json={"worker_id": "reminder-worker", "lease_seconds": 60},
    )
    delivered = await client.post(
        f"/api/v1/jobs/{claimed.json()['id']}/complete",
        headers={**tenant_headers("tenant-a"), "X-Worker-ID": "reminder-worker"},
        json={"result": {"delivered": True}},
    )
    acknowledged = await client.post(
        f"/api/v1/reminders/{first.json()['id']}/acknowledge",
        headers=tenant_headers("tenant-a"),
    )
    jobs = await client.get(
        "/api/v1/jobs",
        headers=tenant_headers("tenant-a"),
        params={"queue": "reminders"},
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert len(reminders.json()) == 1
    assert delivered.status_code == 200
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "acknowledged"
    assert len(jobs.json()) == 1
    assert jobs.json()[0]["job_type"] == "reminder.dispatch"


async def test_durable_job_idempotency_claim_heartbeat_and_duplicate_completion(
    client: AsyncClient,
) -> None:
    headers = tenant_headers("tenant-a")
    payload = {
        "job_type": "notification.send",
        "queue": "notifications",
        "payload": {"message": "Customer update"},
        "backoff_seconds": 0,
    }
    first = await client.post(
        "/api/v1/jobs",
        headers={**headers, "Idempotency-Key": "job-1"},
        json=payload,
    )
    replay = await client.post(
        "/api/v1/jobs",
        headers={**headers, "Idempotency-Key": "job-1"},
        json=payload,
    )
    conflict = await client.post(
        "/api/v1/jobs",
        headers={**headers, "Idempotency-Key": "job-1"},
        json={**payload, "payload": {"message": "Different"}},
    )
    claimed = await client.post(
        "/api/v1/jobs/claim-next?queue=notifications",
        headers=headers,
        json={"worker_id": "worker-1", "lease_seconds": 60},
    )
    heartbeat = await client.post(
        f"/api/v1/jobs/{claimed.json()['id']}/heartbeat",
        headers=headers,
        json={"worker_id": "worker-1", "lease_seconds": 60},
    )
    complete = await client.post(
        f"/api/v1/jobs/{claimed.json()['id']}/complete",
        headers={**headers, "X-Worker-ID": "worker-1"},
        json={"result": {"delivered": True}},
    )
    duplicate_complete = await client.post(
        f"/api/v1/jobs/{claimed.json()['id']}/complete",
        headers={**headers, "X-Worker-ID": "worker-2"},
        json={"result": {"delivered": True}},
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert conflict.status_code == 409
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "running"
    assert claimed.json()["attempts"] == 1
    assert heartbeat.status_code == 200
    assert complete.status_code == 200
    assert complete.json()["status"] == "succeeded"
    assert duplicate_complete.status_code == 200
    assert duplicate_complete.json()["id"] == complete.json()["id"]


async def test_job_retry_dead_letter_manual_recovery_and_lease_expiry(
    client: AsyncClient,
    tmp_path,
) -> None:
    headers = tenant_headers("tenant-a")
    failure_payload = {
        "job_type": "workflow.step",
        "queue": "workflow",
        "payload": {"step": "review_context"},
        "max_attempts": 2,
        "backoff_seconds": 0,
    }
    created = await client.post(
        "/api/v1/jobs",
        headers={**headers, "Idempotency-Key": "retry-job"},
        json=failure_payload,
    )
    claimed_one = await client.post(
        "/api/v1/jobs/claim-next?queue=workflow",
        headers=headers,
        json={"worker_id": "worker-1", "lease_seconds": 60},
    )
    retryable = await client.post(
        f"/api/v1/jobs/{claimed_one.json()['id']}/fail",
        headers={**headers, "X-Worker-ID": "worker-1"},
        json={"error_code": "temporary", "retryable": True},
    )
    claimed_two = await client.post(
        "/api/v1/jobs/claim-next?queue=workflow",
        headers=headers,
        json={"worker_id": "worker-2", "lease_seconds": 60},
    )
    dead_letter = await client.post(
        f"/api/v1/jobs/{claimed_two.json()['id']}/fail",
        headers={**headers, "X-Worker-ID": "worker-2"},
        json={"error_code": "permanent", "retryable": True},
    )
    recovered = await client.post(
        f"/api/v1/jobs/{created.json()['id']}/retry",
        headers=headers,
    )

    expiring = await client.post(
        "/api/v1/jobs",
        headers={**headers, "Idempotency-Key": "lease-job"},
        json={"job_type": "workflow.step", "queue": "lease", "payload": {}},
    )
    claimed_expiring = await client.post(
        "/api/v1/jobs/claim-next?queue=lease",
        headers=headers,
        json={"worker_id": "crashed-worker", "lease_seconds": 60},
    )
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        job = await session.scalar(select(DurableJob).where(DurableJob.id == expiring.json()["id"]))
        assert job is not None
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    await engine.dispose()
    expired = await client.post("/api/v1/jobs/reconcile-expired", headers=headers)

    assert created.status_code == 201
    assert retryable.json()["status"] == "retryable"
    assert dead_letter.json()["status"] == "dead_letter"
    assert recovered.json()["status"] == "queued"
    assert claimed_expiring.json()["id"] == expiring.json()["id"]
    assert expired.status_code == 200
    assert expired.json()[0]["status"] == "retryable"
    assert expired.json()[0]["error_code"] == "worker_lease_expired"


async def test_typed_workflow_can_pause_resume_and_complete(client: AsyncClient) -> None:
    headers = tenant_headers("tenant-a")
    start = await client.post(
        "/api/v1/workflows",
        headers={**headers, "Idempotency-Key": "workflow-1"},
        json={"workflow_key": "customer_follow_up", "input_refs": {"contact_id": "contact-1"}},
    )
    replay = await client.post(
        "/api/v1/workflows",
        headers={**headers, "Idempotency-Key": "workflow-1"},
        json={"workflow_key": "customer_follow_up", "input_refs": {"contact_id": "contact-1"}},
    )
    step_one = await client.post(
        f"/api/v1/workflows/{start.json()['id']}/advance",
        headers={**headers, "If-Match": '"1"'},
        json={"output": {"reviewed": True}},
    )
    step_two = await client.post(
        f"/api/v1/workflows/{start.json()['id']}/advance",
        headers={**headers, "If-Match": '"2"'},
        json={"output": {"commitment_id": "work-1"}},
    )
    paused = await client.post(
        f"/api/v1/workflows/{start.json()['id']}/advance",
        headers={**headers, "If-Match": '"3"'},
        json={"reason": "Approval is required"},
    )
    resumed = await client.post(
        f"/api/v1/workflows/{start.json()['id']}/resume",
        headers={**headers, "If-Match": '"4"'},
    )
    approved = await client.post(
        f"/api/v1/workflows/{start.json()['id']}/advance",
        headers={
            **headers,
            "If-Match": '"5"',
            "X-Correlation-ID": "123e4567-e89b-12d3-a456-426614174000",
        },
        json={"approved": True, "output": {"approved_by": "user-a"}},
    )
    completed = await client.post(
        f"/api/v1/workflows/{start.json()['id']}/advance",
        headers={**headers, "If-Match": '"6"'},
        json={"output": {"finished": True}},
    )
    invalid = await client.post(
        "/api/v1/workflows",
        headers={**headers, "Idempotency-Key": "workflow-invalid"},
        json={"workflow_key": "arbitrary_generated_code"},
    )

    assert start.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["id"] == start.json()["id"]
    assert step_one.json()["current_step"] == 1
    assert step_two.json()["current_step"] == 2
    assert paused.json()["status"] == "paused"
    assert paused.json()["waiting_for"] == "approval"
    assert resumed.json()["status"] == "running"
    assert approved.json()["current_step"] == 3
    assert completed.json()["status"] == "completed"
    assert completed.json()["current_step"] == 4
    assert invalid.status_code == 422
