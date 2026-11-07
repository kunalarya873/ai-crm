from typing import Any

import pytest
from httpx import AsyncClient

from tests.api.agent_helpers import (
    API,
    act,
    deadline,
    get_run,
    headers,
    make_agent,
    start,
    start_raw,
    step,
    task_proposal,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- registry


async def test_register_agent_records_owner_scope_version_and_budget(
    client: AsyncClient,
) -> None:
    agent = await make_agent(client, "renewal-planner", agent_version="v2")

    assert agent["owner_id"] == "user-a"
    assert agent["agent_version"] == "v2"
    assert agent["allowed_actions"] == ["task.create", "contact.update"]
    assert agent["token_budget"] == 10000
    assert agent["status"] == "active"
    listed = await client.get(f"{API}/agents", headers=headers("user-b"))
    assert [item["key"] for item in listed.json()] == ["renewal-planner"]


@pytest.mark.parametrize("user_id", ["user-a", "user-b", "user-c"])
async def test_only_admin_can_register_or_change_agents(
    client: AsyncClient, user_id: str
) -> None:
    agent = await make_agent(client, "planner")
    body = {
        "key": "other",
        "name": "Other",
        "purpose": "x",
        "owner_id": "user-a",
        "token_budget": 10,
        "step_budget": 5,
    }

    create = await client.post(f"{API}/agents", headers=headers(user_id), json=body)
    patch = await client.patch(
        f"{API}/agents/{agent['id']}",
        headers={**headers(user_id), "If-Match": '"1"'},
        json={"name": "Renamed"},
    )

    assert create.status_code == 403
    assert patch.status_code == 403


@pytest.mark.parametrize(
    "overrides",
    [
        {"allowed_actions": ["made.up"]},
        {"allowed_capabilities": ["read"], "allowed_actions": ["task.create"]},
        {"allowed_capabilities": ["propose"], "allowed_actions": []},
        {"allowed_actions": ["integration.activity.create"], "risk_ceiling": "medium"},
        {"max_depth": 99},
        {"token_budget": 10**9},
        {"allowed_capabilities": ["delegate"], "allowed_actions": [], "max_depth": 0},
        {"key": "Bad Key"},
    ],
)
async def test_agent_cannot_register_tools_or_limits_outside_policy(
    client: AsyncClient, overrides: dict[str, Any]
) -> None:
    body = {
        "key": "bad",
        "name": "Bad",
        "purpose": "x",
        "owner_id": "user-a",
        "allowed_capabilities": ["read", "propose"],
        "allowed_actions": ["task.create"],
        "token_budget": 100,
        "step_budget": 5,
    } | overrides

    response = await client.post(f"{API}/agents", headers=headers("user-d"), json=body)

    assert response.status_code == 422


async def test_agent_key_and_owner_validation(client: AsyncClient) -> None:
    await make_agent(client, "planner")
    base = {"name": "P", "purpose": "x", "token_budget": 10, "step_budget": 5}

    duplicate = await client.post(
        f"{API}/agents", headers=headers("user-d"), json=base | {"key": "planner"}
    )
    outsider = await client.post(
        f"{API}/agents",
        headers=headers("user-d"),
        json=base | {"key": "other", "owner_id": "user-e"},
    )

    assert duplicate.status_code == 409
    assert outsider.status_code == 422


async def test_agents_are_tenant_isolated(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    other_tenant = await make_agent(client, "planner", tenant_id="tenant-b")

    foreign = await client.get(f"{API}/agents/{agent['id']}", headers=headers("user-d", "tenant-b"))
    listed = await client.get(f"{API}/agents", headers=headers("user-d", "tenant-b"))
    wrong_tenant_run = await client.post(
        f"{API}/agent-runs",
        headers={**headers("user-a", "tenant-b"), "Idempotency-Key": "x"},
        json={"agent_id": agent["id"], "objective": "o", "deadline_at": deadline()},
    )

    assert foreign.status_code == 404
    assert [item["id"] for item in listed.json()] == [other_tenant["id"]]
    assert wrong_tenant_run.status_code == 404


async def test_agent_update_requires_if_match_and_validates_transitions(
    client: AsyncClient,
) -> None:
    agent = await make_agent(client, "planner")
    url = f"{API}/agents/{agent['id']}"

    missing = await client.patch(url, headers=headers("user-d"), json={"name": "N"})
    stale = await client.patch(
        url, headers={**headers("user-d"), "If-Match": '"9"'}, json={"name": "N"}
    )
    ok = await client.patch(
        url, headers={**headers("user-d"), "If-Match": '"1"'}, json={"status": "retired"}
    )
    revive = await client.patch(
        url, headers={**headers("user-d"), "If-Match": '"2"'}, json={"status": "active"}
    )
    invalid = await client.patch(
        url,
        headers={**headers("user-d"), "If-Match": '"2"'},
        json={"allowed_actions": ["made.up"]},
    )

    assert missing.status_code == 428
    assert stale.status_code == 409
    assert ok.status_code == 200 and ok.json()["version"] == 2
    assert revive.status_code == 409
    assert invalid.status_code == 422


async def test_suspended_agent_cannot_start_or_continue_runs(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)
    suspend = await client.patch(
        f"{API}/agents/{agent['id']}",
        headers={**headers("user-d"), "If-Match": '"1"'},
        json={"status": "suspended"},
    )

    new_run = await start_raw(client, agent, objective="Another", key="k2")
    continued = await step(client, run["id"], "s1", "output", {"summary": "done"})

    assert suspend.status_code == 200
    assert new_run.status_code == 409
    assert continued.status_code == 409


# ---------------------------------------------------------------- runs


async def test_run_records_owner_version_budget_and_trace(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner", agent_version="v3")
    trace = "0af7651916cd43dd8448eb211c80319c"

    run = await start(
        client,
        agent,
        token_budget=500,
        extra_headers={"traceparent": f"00-{trace}-b7ad6b7169203331-01"},
    )

    assert run["owner_id"] == "user-a"
    assert run["agent_key"] == "planner" and run["agent_version"] == "v3"
    assert run["token_budget"] == 500 and run["step_budget"] == 20
    assert run["status"] == "running" and run["depth"] == 0
    assert run["root_run_id"] == run["id"]
    assert run["trace_id"] == trace


async def test_run_start_is_idempotent_and_validated(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    fixed = deadline()
    first = await start(client, agent, key="run-1", deadline_at=fixed)
    replay = await start(client, agent, key="run-1", deadline_at=fixed)
    conflict = await start_raw(
        client, agent, key="run-1", objective="Different", deadline_at=fixed
    )
    past = await start_raw(client, agent, key="k2", hours=-1)
    far = await start_raw(client, agent, key="k3", hours=1000)
    over_budget = await start_raw(client, agent, key="k4", token_budget=10**6)
    naive = await client.post(
        f"{API}/agent-runs",
        headers={**headers(), "Idempotency-Key": "k5"},
        json={"agent_id": agent["id"], "objective": "o", "deadline_at": "2999-01-01T00:00:00"},
    )
    no_key = await client.post(
        f"{API}/agent-runs",
        headers=headers(),
        json={"agent_id": agent["id"], "objective": "o", "deadline_at": deadline()},
    )

    assert replay["id"] == first["id"]
    assert conflict.status_code == 409
    assert {past.status_code, far.status_code, over_budget.status_code} == {422}
    assert naive.status_code == 422
    assert no_key.status_code == 422


async def test_viewer_reads_runs_but_cannot_start_or_act(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)

    read = await client.get(f"{API}/agent-runs", headers=headers("user-b"))
    start_denied = await start_raw(client, agent, user_id="user-b", key="v")
    step_denied = await step(client, run["id"], "s", "output", {"summary": "x"}, user_id="user-b")

    assert read.status_code == 200 and len(read.json()) == 1
    assert start_denied.status_code == 403
    assert step_denied.status_code == 403


async def test_only_owner_can_drive_a_run_and_admin_can_stop_it(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)

    other_step = await step(client, run["id"], "s", "output", {"summary": "x"}, user_id="user-c")
    other_pause = await act(client, run, "pause", user_id="user-c")
    admin_pause = await act(client, run, "pause", user_id="user-d")
    admin_step = await step(client, run["id"], "s", "output", {"summary": "x"}, user_id="user-d")

    assert other_step.status_code == 403
    assert other_pause.status_code == 403
    assert admin_pause.status_code == 200 and admin_pause.json()["status"] == "paused"
    assert admin_step.status_code == 403


async def test_pause_resume_cancel_lifecycle(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)
    url = f"{API}/agent-runs/{run['id']}"

    no_header = await client.post(f"{url}/pause", headers=headers())
    stale = await act(client, run, "pause", version=99)
    paused = await act(client, run, "pause")
    blocked = await step(client, run["id"], "s1", "output", {"summary": "x"})
    resumed = await act(client, run, "resume")
    cancelled = await act(client, run, "cancel")
    after_cancel = await step(client, run["id"], "s2", "output", {"summary": "x"})
    again = await act(client, run, "cancel")
    revive = await act(client, run, "resume")

    assert no_header.status_code == 428
    assert stale.status_code == 409
    assert paused.json()["status"] == "paused"
    assert blocked.status_code == 409
    assert resumed.json()["status"] == "running"
    assert cancelled.json()["status"] == "cancelled"
    assert {after_cancel.status_code, again.status_code, revive.status_code} == {409}


async def test_step_replay_is_idempotent_and_key_reuse_conflicts(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)

    first = await step(client, run["id"], "s1", "propose", task_proposal(), tokens=5)
    replay = await step(client, run["id"], "s1", "propose", task_proposal(), tokens=5)
    reused = await step(client, run["id"], "s1", "propose", task_proposal("Other"), tokens=5)
    detail = await get_run(client, run["id"])

    assert first.status_code == replay.status_code == 201
    assert replay.json()["step"]["id"] == first.json()["step"]["id"]
    assert reused.status_code == 409
    assert len(detail["steps"]) == 1
    assert detail["steps_used"] == 1 and detail["tokens_used"] == 5
    proposals = await client.get(f"{API}/actions/proposals", headers=headers())
    assert len(proposals.json()) == 1


# ---------------------------------------------------------------- tool boundary


async def test_agent_proposal_goes_through_normal_approval_and_separation(
    client: AsyncClient,
) -> None:
    agent = await make_agent(client, "planner", owner_id="user-c")
    run = await start(client, agent, user_id="user-c")

    result = await step(client, run["id"], "p1", "propose", task_proposal(), user_id="user-c")
    proposal_id = result.json()["step"]["action_proposal_id"]
    proposal = (
        await client.get(f"{API}/actions/proposals/{proposal_id}", headers=headers("user-c"))
    ).json()

    approve_by_owner = await client.post(
        f"{API}/actions/proposals/{proposal_id}/approve",
        headers={**headers("user-c"), "If-Match": f'"{proposal["version"]}"'},
        json={"reason": "ok"},
    )
    approve_by_admin = await client.post(
        f"{API}/actions/proposals/{proposal_id}/approve",
        headers={**headers("user-d"), "If-Match": f'"{proposal["version"]}"'},
        json={"reason": "ok"},
    )

    assert proposal["status"] == "proposed" and proposal["requested_by"] == "user-c"
    assert approve_by_owner.status_code == 403
    assert approve_by_owner.json()["code"] == "separation_of_duties"
    assert approve_by_admin.status_code == 200
    detail = await get_run(client, run["id"], "user-c")
    assert detail["side_effects_used"] == 1


@pytest.mark.parametrize(
    ("proposal", "code"),
    [
        ({"action_type": "approval.request", "payload": {"title": "x"}}, "action_not_allowed"),
        (
            {"action_type": "integration.activity.create", "payload": {}},
            "action_not_allowed",
        ),
    ],
)
async def test_unlisted_action_is_denied_escalated_and_creates_nothing(
    client: AsyncClient, proposal: dict[str, Any], code: str
) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)

    result = await step(client, run["id"], "p1", "propose", proposal)
    body = result.json()
    proposals = await client.get(f"{API}/actions/proposals", headers=headers())

    assert result.status_code == 201
    assert body["step"]["status"] == "escalated" and body["step"]["error_code"] == code
    assert body["run"]["status"] == "waiting_human"
    assert body["run"]["escalation_reason"] == "policy_denial"
    assert proposals.json() == []


async def test_agent_cannot_exceed_its_owners_permissions(client: AsyncClient) -> None:
    agent = await make_agent(
        client,
        "writer",
        allowed_actions=["integration.activity.create"],
        risk_ceiling="high",
    )
    run = await start(client, agent, user_id="user-a")  # member: no integrations:write

    result = await step(
        client,
        run["id"],
        "p1",
        "propose",
        {
            "action_type": "integration.activity.create",
            "payload": {"connection_id": "c1", "subject": "Hi"},
        },
    )

    assert result.json()["step"]["error_code"] == "owner_lacks_permission"
    assert result.json()["run"]["status"] == "waiting_human"


async def test_capability_missing_is_a_policy_denial(client: AsyncClient) -> None:
    agent = await make_agent(
        client, "reader", allowed_capabilities=["read"], allowed_actions=[]
    )
    run = await start(client, agent)

    denied = await step(client, run["id"], "p1", "propose", task_proposal())

    assert denied.json()["step"]["error_code"] == "capability_missing"
    assert denied.json()["run"]["escalation_reason"] == "policy_denial"


async def test_duplicate_proposal_is_not_created_twice(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)

    first = await step(client, run["id"], "a", "propose", task_proposal())
    second = await step(client, run["id"], "b", "propose", task_proposal())
    proposals = await client.get(f"{API}/actions/proposals", headers=headers())

    assert second.json()["step"]["output"]["deduplicated"] is True
    assert second.json()["step"]["action_proposal_id"] == first.json()["step"]["action_proposal_id"]
    assert len(proposals.json()) == 1
    assert second.json()["run"]["side_effects_used"] == 1


async def test_side_effect_budget_exhaustion_ends_the_run_with_escalation(
    client: AsyncClient,
) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent, side_effect_budget=1)

    await step(client, run["id"], "a", "propose", task_proposal("One"))
    over = await step(client, run["id"], "b", "propose", task_proposal("Two"))
    after = await step(client, run["id"], "c", "output", {"summary": "x"})

    assert over.json()["run"]["status"] == "budget_exhausted"
    assert over.json()["run"]["escalation_work_item_id"]
    assert after.status_code == 409


async def test_step_and_token_budgets_are_enforced(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    tokens_run = await start(client, agent, token_budget=100, objective="tokens")
    steps_run = await start(client, agent, step_budget=1, objective="steps")

    ok = await step(client, tokens_run["id"], "a", "propose", task_proposal(), tokens=60)
    over_tokens = await step(
        client, tokens_run["id"], "b", "propose", task_proposal("Two"), tokens=60
    )
    await step(client, steps_run["id"], "a", "propose", task_proposal("Three"))
    over_steps = await step(client, steps_run["id"], "b", "propose", task_proposal("Four"))

    assert ok.json()["run"]["tokens_used"] == 60
    assert over_tokens.json()["run"]["status"] == "budget_exhausted"
    assert over_tokens.json()["run"]["tokens_used"] == 60
    assert over_steps.json()["run"]["status"] == "budget_exhausted"


async def _knowledge_source(client: AsyncClient, sensitivity: str) -> None:
    created = await client.post(
        f"{API}/knowledge/sources",
        headers=headers("user-c"),
        json={
            "source_type": "document",
            "source_record_id": f"doc-{sensitivity}",
            "title": "Pricing memo",
            "content": "renewal pricing discount details",
            "sensitivity": sensitivity,
        },
    )
    assert created.status_code == 201
    queued = await client.post(
        f"{API}/knowledge/sources/{created.json()['id']}/index", headers=headers("user-c")
    )
    ran = await client.post(
        f"{API}/knowledge/index-jobs/{queued.json()['id']}/run", headers=headers("user-c")
    )
    assert ran.status_code == 200


async def test_retrieval_honours_agent_scope_and_owner_permissions(client: AsyncClient) -> None:
    await _knowledge_source(client, "sensitive")
    plain = await make_agent(client, "plain", allow_sensitive=False)
    scoped = await make_agent(client, "scoped", allow_sensitive=True)
    query = {"query": "renewal pricing"}

    plain_run = await start(client, plain, user_id="user-c")
    scoped_run = await start(client, scoped, user_id="user-c")
    member_run = await start(
        client, scoped, user_id="user-a", objective="Member run"
    )  # member lacks sensitive
    plain_result = await step(client, plain_run["id"], "r", "retrieve", query, user_id="user-c")
    scoped_result = await step(client, scoped_run["id"], "r", "retrieve", query, user_id="user-c")
    member_result = await step(client, member_run["id"], "r", "retrieve", query)

    assert plain_result.json()["step"]["output"]["insufficient_evidence"] is True
    assert scoped_result.json()["step"]["output"]["insufficient_evidence"] is False
    assert len(scoped_result.json()["step"]["output"]["citations"]) == 1
    assert member_result.json()["step"]["output"]["insufficient_evidence"] is True
    assert scoped_result.json()["step"]["context_assembly_id"]


async def test_retrieve_without_read_capability_is_denied(client: AsyncClient) -> None:
    agent = await make_agent(
        client, "writer", allowed_capabilities=["propose"], allowed_actions=["task.create"]
    )
    run = await start(client, agent)

    denied = await step(client, run["id"], "r", "retrieve", {"query": "x"})

    assert denied.json()["step"]["error_code"] == "capability_missing"


async def test_invalid_step_input_is_a_validation_error_not_a_step(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)

    bad = await step(client, run["id"], "p", "propose", {"action_type": "task.create", "x": 1})
    unknown_type = await client.post(
        f"{API}/agent-runs/{run['id']}/steps",
        headers=headers(),
        json={"step_key": "u", "step_type": "shell", "input": {}},
    )
    detail = await get_run(client, run["id"])

    assert bad.status_code == 422
    assert unknown_type.status_code == 422
    assert detail["steps"] == [] and detail["steps_used"] == 0


async def test_cross_tenant_run_ids_are_not_found(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)

    read = await client.get(f"{API}/agent-runs/{run['id']}", headers=headers("user-d", "tenant-b"))
    acted = await client.post(
        f"{API}/agent-runs/{run['id']}/steps",
        headers=headers("user-a", "tenant-b"),
        json={"step_key": "s", "step_type": "output", "input": {"summary": "x"}},
    )
    paused = await client.post(
        f"{API}/agent-runs/{run['id']}/pause",
        headers={**headers("user-d", "tenant-b"), "If-Match": '"1"'},
    )

    assert read.status_code == 404
    assert acted.status_code == 404
    assert paused.status_code == 404


async def test_dedup_retry_costs_nothing_even_when_side_effect_budget_is_spent(
    client: AsyncClient,
) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent, side_effect_budget=1)

    await step(client, run["id"], "a", "propose", task_proposal())
    retry = await step(client, run["id"], "b", "propose", task_proposal())

    assert retry.json()["step"]["output"]["deduplicated"] is True
    assert retry.json()["run"]["status"] == "running"


async def test_idempotency_replay_is_scoped_to_the_owner_and_prefix_is_reserved(
    client: AsyncClient,
) -> None:
    agent = await make_agent(client, "planner")
    fixed = deadline()
    await start(client, agent, key="shared", deadline_at=fixed)

    other_user = await start_raw(
        client, agent, user_id="user-c", key="shared", deadline_at=fixed
    )
    reserved = await start_raw(client, agent, key="delegate:abc:def", objective="reserved")

    assert other_user.status_code == 409
    assert reserved.status_code == 422


async def test_status_only_update_is_not_blocked_by_tightened_platform_caps(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_crm.config import settings

    agent = await make_agent(client, "planner", token_budget=5000)
    monkeypatch.setattr(settings, "agent_token_budget_cap", 100)

    suspend = await client.patch(
        f"{API}/agents/{agent['id']}",
        headers={**headers("user-d"), "If-Match": '"1"'},
        json={"status": "suspended"},
    )
    raise_budget = await client.patch(
        f"{API}/agents/{agent['id']}",
        headers={**headers("user-d"), "If-Match": '"2"'},
        json={"token_budget": 6000},
    )

    assert suspend.status_code == 200
    assert raise_budget.status_code == 422
