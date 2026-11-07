from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_crm.actions.service import create_proposal
from ai_crm.api.deps import RequestContext
from ai_crm.models import AgentRun, AuditEvent
from ai_crm.permissions import ROLE_PERMISSIONS
from ai_crm.schemas import ActionProposalCreate
from ai_crm.work.runner import run_tick
from tests.api.agent_helpers import (
    API,
    act,
    get_run,
    headers,
    make_agent,
    start,
    step,
    task_proposal,
)

pytestmark = pytest.mark.asyncio

Factory = async_sessionmaker[AsyncSession]
REASONS = [
    "uncertainty",
    "policy_denial",
    "missing_context",
    "sensitive_action",
    "conflicting_outputs",
    "budget_exhausted",
    "repeated_failure",
    "deadline_exceeded",
]


async def escalate(client: AsyncClient, run_id: str, reason: str = "uncertainty", key: str = "e"):
    return await step(
        client,
        run_id,
        key,
        "escalate",
        {
            "reason": reason,
            "summary": "Customer asked for a discount I cannot grant",
            "evidence_refs": [{"type": "contact", "id": "c-1"}],
            "proposed_next_steps": ["Call the customer", "Offer a standard plan"],
        },
    )


async def complete_work_item(client: AsyncClient, work_item_id: str) -> None:
    base = f"{API}/work-items/{work_item_id}/transition"
    started = await client.post(
        base, headers={**headers(), "If-Match": '"1"'}, json={"to_status": "in_progress"}
    )
    assert started.status_code == 200
    done = await client.post(
        base,
        headers={**headers(), "If-Match": '"2"'},
        json={"to_status": "completed", "evidence": "Handled by phone"},
    )
    assert done.status_code == 200


@pytest.mark.parametrize("reason", REASONS)
async def test_escalation_creates_a_human_work_item_with_evidence(
    client: AsyncClient, reason: str
) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent, objective=f"Close {reason}")

    result = await escalate(client, run["id"], reason)
    body = result.json()
    item = (
        await client.get(
            f"{API}/work-items/{body['run']['escalation_work_item_id']}", headers=headers()
        )
    ).json()
    messages = await client.get(f"{API}/agent-runs/{run['id']}/messages", headers=headers())
    blocked = await step(client, run["id"], "next", "output", {"summary": "x"})

    assert result.status_code == 201
    assert body["run"]["status"] == "waiting_human" and body["run"]["escalation_reason"] == reason
    assert item["item_type"] == "escalation" and item["assignee_id"] == "user-a"
    assert "discount" in item["description"] and "c-1" in item["description"]
    assert "Call the customer" in item["description"] and run["id"] in item["description"]
    assert [m["kind"] for m in messages.json()] == ["escalation"]
    assert messages.json()[0]["body"]["work_item_id"] == item["id"]
    assert blocked.status_code == 409


async def test_resume_requires_completed_work_item_current_version_and_active_agent(
    client: AsyncClient,
) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)
    escalated = (await escalate(client, run["id"])).json()["run"]

    too_early = await act(client, escalated, "resume")
    await complete_work_item(client, escalated["escalation_work_item_id"])
    stale = await act(client, escalated, "resume", version=escalated["version"] - 1)
    resumed = await act(client, escalated, "resume")
    after = await step(client, run["id"], "next", "output", {"summary": "done"})

    assert too_early.status_code == 409
    assert stale.status_code == 409
    assert resumed.json()["status"] == "running"
    assert resumed.json()["escalation_work_item_id"] is None
    assert after.json()["run"]["status"] == "completed"


async def test_resume_is_blocked_when_the_agent_was_suspended(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)
    escalated = (await escalate(client, run["id"])).json()["run"]
    await complete_work_item(client, escalated["escalation_work_item_id"])
    await client.patch(
        f"{API}/agents/{agent['id']}",
        headers={**headers("user-d"), "If-Match": '"1"'},
        json={"status": "suspended"},
    )

    resumed = await act(client, escalated, "resume")

    assert resumed.status_code == 409


async def test_agent_without_escalate_capability_is_denied_but_still_hands_off(
    client: AsyncClient,
) -> None:
    agent = await make_agent(
        client, "quiet", allowed_capabilities=["read"], allowed_actions=[]
    )
    run = await start(client, agent)

    result = await escalate(client, run["id"])

    assert result.json()["step"]["error_code"] == "capability_missing"
    assert result.json()["run"]["escalation_reason"] == "policy_denial"


async def test_agent_reported_failure_and_success_are_terminal(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    ok = await start(client, agent, objective="ok")
    bad = await start(client, agent, objective="bad")

    done = await step(client, ok["id"], "o", "output", {"summary": "fine", "result": {"n": 1}})
    failed = await step(
        client, bad["id"], "o", "output", {"outcome": "failed", "summary": "broke"}
    )

    assert done.json()["run"]["status"] == "completed"
    assert done.json()["run"]["terminal_reason"] == "completed"
    assert done.json()["run"]["completed_at"] is not None
    assert failed.json()["run"]["status"] == "failed"
    assert failed.json()["run"]["terminal_reason"] == "agent_reported_failure"


async def _expire(factory: Factory, *run_ids: str) -> None:
    async with factory() as session:
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id.in_(run_ids))
            .values(deadline_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()


async def test_worker_fails_overdue_runs_and_escalates(
    client: AsyncClient, session_factory: Factory
) -> None:
    agent = await make_agent(client, "planner")
    other_tenant = await make_agent(client, "planner", tenant_id="tenant-b", owner_id="user-a")
    running = await start(client, agent, objective="running")
    paused = await start(client, agent, objective="paused")
    waiting = await start(client, agent, objective="waiting")
    finished = await start(client, agent, objective="finished")
    healthy = await start(client, agent, objective="healthy")
    foreign = (
        await client.post(
            f"{API}/agent-runs",
            headers={**headers("user-a", "tenant-b"), "Idempotency-Key": "t-b"},
            json={
                "agent_id": other_tenant["id"],
                "objective": "foreign",
                "deadline_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
        )
    ).json()
    await act(client, paused, "pause")
    await escalate(client, waiting["id"])
    await step(client, finished["id"], "o", "output", {"summary": "done"})
    await _expire(session_factory, running["id"], paused["id"], waiting["id"], finished["id"])
    await _expire(session_factory, foreign["id"])

    await run_tick(session_factory)
    states = {
        name: await get_run(client, run["id"])
        for name, run in [
            ("running", running),
            ("paused", paused),
            ("waiting", waiting),
            ("finished", finished),
            ("healthy", healthy),
        ]
    }
    async with session_factory() as session:
        foreign_row = await session.get_one(AgentRun, foreign["id"])

    for name in ("running", "paused", "waiting"):
        assert states[name]["status"] == "failed"
        assert states[name]["terminal_reason"] == "deadline_exceeded"
    assert states["running"]["escalation_work_item_id"]
    assert states["paused"]["escalation_work_item_id"]
    assert states["finished"]["status"] == "completed"
    assert states["healthy"]["status"] == "running"
    assert foreign_row.status == "failed"


async def test_step_after_deadline_fails_the_run(
    client: AsyncClient, session_factory: Factory
) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)
    await _expire(session_factory, run["id"])

    late = await step(client, run["id"], "s", "output", {"summary": "late"})
    detail = await get_run(client, run["id"])

    assert late.status_code == 409
    assert detail["status"] == "failed" and detail["terminal_reason"] == "deadline_exceeded"
    assert detail["escalation_work_item_id"]


async def test_audit_chain_links_run_step_and_proposal(
    client: AsyncClient, session_factory: Factory
) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)

    result = await step(client, run["id"], "p", "propose", task_proposal())
    step_body = result.json()["step"]
    async with session_factory() as session:
        events = list(
            await session.scalars(select(AuditEvent).where(AuditEvent.tenant_id == "tenant-a"))
        )
    by_action = {event.action: event for event in events}

    assert {"agent.registered", "agent.run.started", "agent.step.recorded"} <= set(by_action)
    assert "action.proposal.created" in by_action
    recorded = by_action["agent.step.recorded"]
    assert recorded.entity_id == step_body["id"]
    assert recorded.details["run_id"] == run["id"]
    assert recorded.details["agent_key"] == "planner"
    assert recorded.details["action_proposal_id"] == step_body["action_proposal_id"]
    assert by_action["action.proposal.created"].entity_id == step_body["action_proposal_id"]


async def test_replayed_step_after_a_crash_reuses_the_proposal(
    client: AsyncClient, session_factory: Factory
) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)
    # Simulate a driver crash after the proposal committed but before the step was recorded.
    context = RequestContext(
        tenant_id="tenant-a",
        actor_id="user-a",
        role="member",
        correlation_id="crash",
        permissions=ROLE_PERMISSIONS["member"],
    )
    async with session_factory() as session:
        orphan = await create_proposal(
            session,
            context,
            ActionProposalCreate(**task_proposal()),
            f"agent:{run['id']}:p",
        )

    retried = await step(client, run["id"], "p", "propose", task_proposal())
    proposals = await client.get(f"{API}/actions/proposals", headers=headers())

    assert retried.json()["step"]["action_proposal_id"] == orphan.id
    assert len(proposals.json()) == 1
    assert retried.json()["run"]["side_effects_used"] == 1


async def test_cancelled_run_keeps_its_audit_trail_and_cannot_resume(
    client: AsyncClient,
) -> None:
    agent = await make_agent(client, "planner")
    run = await start(client, agent)
    escalated = (await escalate(client, run["id"])).json()["run"]
    await complete_work_item(client, escalated["escalation_work_item_id"])

    cancelled = await act(client, escalated, "cancel")
    revived = await act(client, escalated, "resume")

    assert cancelled.json()["status"] == "cancelled"
    assert revived.status_code == 409
    detail: dict[str, Any] = await get_run(client, run["id"])
    assert detail["terminal_reason"] == "cancelled_by_user"
