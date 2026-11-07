import asyncio
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


async def create_contact(client: AsyncClient) -> dict[str, object]:
    response = await client.post(
        "/api/v1/contacts",
        headers=tenant_headers("tenant-a"),
        json={"first_name": "Ada", "last_name": "Lovelace"},
    )
    assert response.status_code == 201
    return response.json()


async def create_proposal(
    client: AsyncClient,
    action_type: str,
    payload: dict[str, object],
    *,
    key: str,
    expires_at: str | None = None,
    user_id: str = "user-a",
) -> dict[str, object]:
    body: dict[str, object] = {"action_type": action_type, "payload": payload}
    if expires_at is not None:
        body["expires_at"] = expires_at
    response = await client.post(
        "/api/v1/actions/proposals",
        headers={**tenant_headers("tenant-a", user_id), "Idempotency-Key": key},
        json=body,
    )
    assert response.status_code == 201
    return response.json()


async def approve(client: AsyncClient, proposal: dict[str, object]) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/approve",
        headers={**tenant_headers("tenant-a", "user-c"), "If-Match": f'"{proposal["version"]}"'},
        json={"reason": "Reviewed and approved"},
    )
    assert response.status_code == 200
    return response.json()


async def test_action_registry_dry_run_idempotency_and_approval_gate(
    client: AsyncClient,
) -> None:
    registry = await client.get(
        "/api/v1/actions/registry",
        headers=tenant_headers("tenant-a"),
    )
    dry_run = await client.post(
        "/api/v1/actions/dry-run?action_type=task.create",
        headers=tenant_headers("tenant-a"),
        json={"title": "Dry-run task", "priority": "high"},
    )
    proposal = await create_proposal(
        client,
        "task.create",
        {"title": "Approved task", "priority": "high"},
        key="action-task-1",
    )
    replay = await create_proposal(
        client,
        "task.create",
        {"title": "Approved task", "priority": "high"},
        key="action-task-1",
    )
    before_approval = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/execute",
        headers={**tenant_headers("tenant-a"), "If-Match": '"1"'},
    )

    assert registry.status_code == 200
    assert any(item["action_type"] == "task.create" for item in registry.json())
    assert dry_run.status_code == 200
    assert dry_run.json()["valid"] is True
    assert dry_run.json()["requires_approval"] is True
    assert replay["id"] == proposal["id"]
    assert before_approval.status_code == 409


async def test_approved_task_action_executes_once_and_is_auditable(client: AsyncClient) -> None:
    proposal = await create_proposal(
        client,
        "task.create",
        {"title": "Create from action", "description": "Created after approval"},
        key="action-task-execute",
    )
    approved = await approve(client, proposal)
    execution = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/execute",
        headers={**tenant_headers("tenant-a"), "If-Match": f'"{approved["version"]}"'},
    )
    executions = await client.get(
        "/api/v1/actions/executions",
        headers=tenant_headers("tenant-a"),
    )
    proposal_read = await client.get(
        f"/api/v1/actions/proposals/{proposal['id']}",
        headers=tenant_headers("tenant-a"),
    )
    duplicate = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/execute",
        headers={**tenant_headers("tenant-a"), "If-Match": '"3"'},
    )

    assert execution.status_code == 200
    assert execution.json()["status"] == "succeeded"
    assert execution.json()["result"]["entity_type"] == "task"
    assert len(executions.json()) == 1
    assert proposal_read.json()["status"] == "succeeded"
    assert duplicate.status_code == 409


async def test_contact_action_rechecks_record_version_at_execution(client: AsyncClient) -> None:
    contact = await create_contact(client)
    proposal = await create_proposal(
        client,
        "contact.update",
        {
            "contact_id": contact["id"],
            "expected_version": 1,
            "changes": {"status": "qualified"},
        },
        key="action-contact-version",
    )
    approved = await approve(client, proposal)
    changed = await client.patch(
        f"/api/v1/contacts/{contact['id']}",
        headers={**tenant_headers("tenant-a"), "If-Match": '"1"'},
        json={"first_name": "Augusta"},
    )
    execution = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/execute",
        headers={**tenant_headers("tenant-a"), "If-Match": f'"{approved["version"]}"'},
    )

    assert changed.status_code == 200, changed.text
    assert execution.status_code == 200
    assert execution.json()["status"] == "failed"
    assert execution.json()["error_code"] == "record_version_conflict"


async def test_edit_requires_reapproval_and_approval_action_creates_work_item(
    client: AsyncClient,
) -> None:
    proposal = await create_proposal(
        client,
        "approval.request",
        {"title": "Approve customer discount", "description": "Finance review"},
        key="action-approval-request",
    )
    edited = await client.patch(
        f"/api/v1/actions/proposals/{proposal['id']}",
        headers={**tenant_headers("tenant-a"), "If-Match": '"1"'},
        json={"payload": {"title": "Approve revised discount", "assignee_id": "user-a"}},
    )
    blocked = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/execute",
        headers={**tenant_headers("tenant-a"), "If-Match": '"2"'},
    )
    approved = await approve(client, edited.json())
    executed = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/execute",
        headers={**tenant_headers("tenant-a"), "If-Match": f'"{approved["version"]}"'},
    )
    work_items = await client.get(
        "/api/v1/work-items",
        headers=tenant_headers("tenant-a"),
        params={"item_type": "approval"},
    )

    assert edited.status_code == 200
    assert edited.json()["status"] == "edited"
    assert blocked.status_code == 409
    assert executed.status_code == 200
    assert executed.json()["status"] == "succeeded"
    assert work_items.status_code == 200
    assert work_items.json()[0]["title"] == "Approve revised discount"


async def test_expired_proposal_and_viewer_permissions(client: AsyncClient) -> None:
    expired = await create_proposal(
        client,
        "task.create",
        {"title": "Expired action"},
        key="action-expired",
        expires_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
    )
    await asyncio.sleep(1.1)
    viewer_create = await client.post(
        "/api/v1/actions/proposals",
        headers={**tenant_headers("tenant-a", "user-b"), "Idempotency-Key": "viewer-action"},
        json={"action_type": "task.create", "payload": {"title": "Nope"}},
    )
    future = await client.post(
        "/api/v1/actions/proposals/expire",
        headers=tenant_headers("tenant-a", "user-c"),
    )

    assert expired["status"] == "proposed"
    assert viewer_create.status_code == 403
    assert future.status_code == 200
    assert future.json()[0]["id"] == expired["id"]
    assert future.json()[0]["status"] == "expired"


async def test_external_action_uses_fixture_write_and_effect_idempotency(
    client: AsyncClient,
) -> None:
    connection = await client.post(
        "/api/v1/integrations/connections",
        headers=tenant_headers("tenant-a", "user-d"),
        json={
            "provider_key": "fixture",
            "external_account_id": "action-external-account",
            "scopes": ["activities:write"],
            "secret_ref": "fixture-secret",
        },
    )
    assert connection.status_code == 201
    proposal = await create_proposal(
        client,
        "integration.activity.create",
        {
            "connection_id": connection.json()["id"],
            "subject": "Approved external activity",
            "body": "Created through the action runtime",
        },
        key="action-external-1",
        user_id="user-d",
    )
    approved = await approve(client, proposal)
    execution = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/execute",
        headers={**tenant_headers("tenant-a", "user-d"), "If-Match": f'"{approved["version"]}"'},
    )
    executions = await client.get(
        "/api/v1/actions/executions",
        headers=tenant_headers("tenant-a"),
    )

    assert execution.status_code == 200
    assert execution.json()["status"] == "succeeded"
    assert execution.json()["provider_request_id"].startswith("fixture-request-action:")
    assert execution.json()["result"]["external_write_id"]
    assert len(executions.json()) == 1


async def test_uncertain_external_action_requires_reconciliation_before_retry(
    client: AsyncClient,
) -> None:
    connection = await client.post(
        "/api/v1/integrations/connections",
        headers=tenant_headers("tenant-a", "user-d"),
        json={
            "provider_key": "fixture",
            "external_account_id": "action-uncertain-account",
            "scopes": ["activities:write"],
            "secret_ref": "fixture-secret",
            "configuration": {"write_failure": "uncertain"},
        },
    )
    proposal = await create_proposal(
        client,
        "integration.activity.create",
        {
            "connection_id": connection.json()["id"],
            "subject": "Uncertain external activity",
        },
        key="action-uncertain-1",
        user_id="user-d",
    )
    approved = await approve(client, proposal)
    execution = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/execute",
        headers={**tenant_headers("tenant-a", "user-d"), "If-Match": f'"{approved["version"]}"'},
    )
    retry = await client.post(
        f"/api/v1/actions/executions/{execution.json()['id']}/retry",
        headers=tenant_headers("tenant-a", "user-c"),
        json={"operator_note": "Do not retry until provider outcome is reconciled"},
    )

    assert execution.status_code == 200
    assert execution.json()["status"] == "uncertain"
    assert execution.json()["uncertain_outcome"] is True
    assert retry.status_code == 409


async def test_requester_cannot_approve_own_proposal_and_denial_is_audited(
    client: AsyncClient,
) -> None:
    proposal = await create_proposal(
        client, "task.create", {"title": "Self approval"}, key="self-approve-1", user_id="user-c"
    )
    own = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/approve",
        headers={**tenant_headers("tenant-a", "user-c"), "If-Match": f'"{proposal["version"]}"'},
        json={"reason": "I approve myself"},
    )
    other = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/approve",
        headers={**tenant_headers("tenant-a", "user-d"), "If-Match": f'"{proposal["version"]}"'},
        json={"reason": "Independent review"},
    )

    assert own.status_code == 403
    assert own.json()["code"] == "separation_of_duties"
    assert other.status_code == 200
    assert other.json()["approved_by"] == "user-d"


async def test_member_can_propose_but_not_approve(client: AsyncClient) -> None:
    proposal = await create_proposal(
        client, "task.create", {"title": "Member proposal"}, key="member-approve-1"
    )
    denied = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/approve",
        headers={**tenant_headers("tenant-a", "user-a"), "If-Match": f'"{proposal["version"]}"'},
        json={"reason": "Not allowed"},
    )
    approved = await approve(client, proposal)

    assert denied.status_code == 403
    assert approved["status"] == "approved"


async def test_editor_cannot_approve_and_reapproval_status_wins(client: AsyncClient) -> None:
    proposal = await create_proposal(
        client, "task.create", {"title": "Edited"}, key="editor-approve-1"
    )
    edited = await client.patch(
        f"/api/v1/actions/proposals/{proposal['id']}",
        headers={**tenant_headers("tenant-a", "user-d"), "If-Match": '"1"'},
        json={"payload": {"title": "Edited by admin"}},
    )
    editor_approve = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/approve",
        headers={**tenant_headers("tenant-a", "user-d"), "If-Match": '"2"'},
        json={"reason": "Own edit"},
    )

    assert edited.json()["last_edited_by"] == "user-d"
    assert editor_approve.status_code == 403
    assert editor_approve.json()["code"] == "separation_of_duties"


async def test_state_error_wins_over_self_approval_denial(client: AsyncClient) -> None:
    proposal = await create_proposal(
        client, "task.create", {"title": "Mgr"}, key="state-first-1", user_id="user-c"
    )
    approved = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/approve",
        headers={**tenant_headers("tenant-a", "user-d"), "If-Match": '"1"'},
        json={"reason": "ok"},
    )
    repeat = await client.post(
        f"/api/v1/actions/proposals/{proposal['id']}/approve",
        headers={
            **tenant_headers("tenant-a", "user-c"),
            "If-Match": f'"{approved.json()["version"]}"',
        },
        json={"reason": "again"},
    )

    assert repeat.status_code == 409
    assert repeat.json()["code"] == "invalid_transition"
