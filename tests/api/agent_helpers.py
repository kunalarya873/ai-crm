from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient, Response

from ai_crm.auth import create_access_token

API = "/api/v1"


def headers(user_id: str = "user-a", tenant_id: str = "tenant-a") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-ID": tenant_id,
    }


def deadline(hours: float = 1) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


async def make_agent(
    client: AsyncClient, key: str, tenant_id: str = "tenant-a", **overrides: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "key": key,
        "name": key.title(),
        "purpose": "test agent",
        "owner_id": "user-a",
        "allowed_capabilities": ["read", "propose", "delegate", "escalate"],
        "allowed_actions": ["task.create", "contact.update"],
        "risk_ceiling": "medium",
        "max_depth": 2,
        "max_fanout": 3,
        "token_budget": 10000,
        "step_budget": 20,
        "side_effect_budget": 3,
    }
    body.update(overrides)
    response = await client.post(
        f"{API}/agents", headers=headers("user-d", tenant_id), json=body
    )
    assert response.status_code == 201, response.text
    return response.json()


async def start(
    client: AsyncClient,
    agent: dict[str, Any],
    *,
    user_id: str = "user-a",
    objective: str = "Prepare the renewal",
    key: str | None = None,
    hours: float = 1,
    extra_headers: dict[str, str] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    response = await start_raw(
        client, agent, user_id=user_id, objective=objective, key=key, hours=hours,
        extra_headers=extra_headers, **fields,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def start_raw(
    client: AsyncClient,
    agent: dict[str, Any],
    *,
    user_id: str = "user-a",
    objective: str = "Prepare the renewal",
    key: str | None = None,
    hours: float = 1,
    extra_headers: dict[str, str] | None = None,
    **fields: Any,
) -> Response:
    return await client.post(
        f"{API}/agent-runs",
        headers={
            **headers(user_id),
            "Idempotency-Key": key or f"run-{agent['key']}-{objective}",
            **(extra_headers or {}),
        },
        json={"agent_id": agent["id"], "objective": objective, "deadline_at": deadline(hours)}
        | fields,
    )


async def step(
    client: AsyncClient,
    run_id: str,
    key: str,
    step_type: str,
    payload: dict[str, Any] | None = None,
    *,
    user_id: str = "user-a",
    tokens: int = 0,
) -> Response:
    return await client.post(
        f"{API}/agent-runs/{run_id}/steps",
        headers=headers(user_id),
        json={"step_key": key, "step_type": step_type, "input": payload or {}, "tokens": tokens},
    )


async def get_run(client: AsyncClient, run_id: str, user_id: str = "user-a") -> dict[str, Any]:
    response = await client.get(f"{API}/agent-runs/{run_id}", headers=headers(user_id))
    assert response.status_code == 200, response.text
    return response.json()


async def act(
    client: AsyncClient,
    run: dict[str, Any],
    action: str,
    *,
    user_id: str = "user-a",
    version: object | None = None,
) -> Response:
    current = await get_run(client, run["id"], user_id)
    return await client.post(
        f"{API}/agent-runs/{run['id']}/{action}",
        headers={
            **headers(user_id),
            "If-Match": f'"{current["version"] if version is None else version}"',
        },
    )


def task_proposal(title: str = "Follow up") -> dict[str, Any]:
    return {"action_type": "task.create", "payload": {"title": title}}


async def make_contact(client: AsyncClient) -> dict[str, Any]:
    response = await client.post(
        f"{API}/contacts",
        headers=headers("user-a"),
        json={"first_name": "Ada", "last_name": "Lovelace"},
    )
    assert response.status_code == 201
    return response.json()


def contact_update(contact: dict[str, Any], first_name: str) -> dict[str, Any]:
    return {
        "action_type": "contact.update",
        "payload": {
            "contact_id": contact["id"],
            "expected_version": contact["version"],
            "changes": {"first_name": first_name},
        },
    }
