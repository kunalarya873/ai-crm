from typing import Any

import pytest
from httpx import AsyncClient

from tests.api.agent_helpers import (
    API,
    act,
    contact_update,
    deadline,
    get_run,
    headers,
    make_agent,
    make_contact,
    start,
    step,
)

pytestmark = pytest.mark.asyncio


def delegation(agent_key: str, objective: str, **overrides: Any) -> dict[str, Any]:
    return {
        "agent_key": agent_key,
        "reason": "Needs specialist input",
        "objective": objective,
        "expected_result": "A short summary",
        "deadline_at": deadline(0.5),
        "token_budget": 1000,
        "step_budget": 5,
        "side_effect_budget": 1,
    } | overrides


async def delegate(
    client: AsyncClient, run_id: str, key: str, agent_key: str, objective: str, **over: Any
):
    return await step(client, run_id, key, "delegate", delegation(agent_key, objective, **over))


async def last_step(client: AsyncClient, run_id: str) -> dict[str, Any]:
    return (await get_run(client, run_id))["steps"][-1]


async def team(client: AsyncClient, **planner: Any) -> dict[str, dict[str, Any]]:
    return {
        "planner": await make_agent(client, "planner", **planner),
        "researcher": await make_agent(client, "researcher"),
        "writer": await make_agent(
            client,
            "writer",
            allowed_capabilities=["read", "propose"],
            max_depth=0,
            max_fanout=0,
        ),
    }


async def test_delegation_creates_a_bounded_persisted_child_run(client: AsyncClient) -> None:
    agents = await team(client)
    parent = await start(client, agents["planner"], token_budget=5000)

    result = await delegate(client, parent["id"], "d1", "researcher", "Research pricing")
    child_id = result.json()["step"]["child_run_id"]
    child = await get_run(client, child_id)
    parent_after = result.json()["run"]
    messages = await client.get(f"{API}/agent-runs/{parent['id']}/messages", headers=headers())

    assert result.status_code == 201
    assert child["parent_run_id"] == parent["id"] and child["root_run_id"] == parent["id"]
    assert child["depth"] == 1 and child["owner_id"] == "user-a"
    assert child["token_budget"] == 1000 and child["step_budget"] == 5
    assert child["agent_key"] == "researcher" and child["status"] == "running"
    assert parent_after["tokens_used"] == 1000 and parent_after["side_effects_used"] == 1
    assert [m["kind"] for m in messages.json()] == ["delegation"]
    assert messages.json()[0]["body"]["reason"] == "Needs specialist input"
    assert messages.json()[0]["to_run_id"] == child_id


async def test_child_result_reaches_parent_and_parent_cannot_finish_early(
    client: AsyncClient,
) -> None:
    agents = await team(client)
    parent = await start(client, agents["planner"])
    child_id = (await delegate(client, parent["id"], "d1", "researcher", "Research")).json()[
        "step"
    ]["child_run_id"]

    early = await step(client, parent["id"], "o1", "output", {"summary": "done"})
    early_step = await last_step(client, parent["id"])
    child_done = await step(client, child_id, "c1", "output", {"summary": "found it"})
    finished = await step(client, parent["id"], "o2", "output", {"summary": "done"})
    messages = await client.get(f"{API}/agent-runs/{parent['id']}/messages", headers=headers())

    assert early.status_code == 409
    assert early_step["error_code"] == "children_active"
    assert child_done.json()["run"]["status"] == "completed"
    assert finished.json()["run"]["status"] == "completed"
    assert [m["kind"] for m in messages.json()] == ["delegation", "result"]
    assert messages.json()[1]["body"]["status"] == "completed"


async def test_cycles_including_self_delegation_are_rejected(client: AsyncClient) -> None:
    agents = await team(client)
    parent = await start(client, agents["planner"])
    child_id = (await delegate(client, parent["id"], "d1", "researcher", "Research")).json()[
        "step"
    ]["child_run_id"]

    self_delegation = await delegate(client, parent["id"], "d2", "planner", "Plan again")
    back_edge = await delegate(client, child_id, "d3", "planner", "Plan from child")

    assert self_delegation.status_code == 409
    assert back_edge.status_code == 409
    assert (await last_step(client, child_id))["error_code"] == "delegation_cycle"
    assert (await last_step(client, parent["id"]))["error_code"] == "delegation_cycle"


async def test_delegation_depth_is_bounded(client: AsyncClient) -> None:
    agents = await team(client, max_depth=1)
    parent = await start(client, agents["planner"])
    child_id = (await delegate(client, parent["id"], "d1", "researcher", "Research")).json()[
        "step"
    ]["child_run_id"]

    too_deep = await delegate(client, child_id, "d2", "writer", "Write it up")

    assert too_deep.status_code == 409
    assert (await last_step(client, child_id))["error_code"] == "max_depth_exceeded"


async def test_delegation_fanout_is_bounded(client: AsyncClient) -> None:
    agents = await team(client, max_fanout=1)
    parent = await start(client, agents["planner"])

    first = await delegate(client, parent["id"], "d1", "researcher", "Research")
    second = await delegate(client, parent["id"], "d2", "writer", "Write")

    assert first.status_code == 201
    assert second.status_code == 409
    assert (await last_step(client, parent["id"]))["error_code"] == "max_fanout_exceeded"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"token_budget": 5000}, "insufficient_token_budget"),
        ({"step_budget": 999}, "exceeds_target_agent_limits"),
        ({"side_effect_budget": 3}, "insufficient_side_effect_budget"),
        ({"deadline_at": deadline(5)}, "invalid_deadline"),
        ({"deadline_at": deadline(-1)}, "invalid_deadline"),
    ],
)
async def test_delegation_budget_and_deadline_limits(
    client: AsyncClient, overrides: dict[str, Any], code: str
) -> None:
    agents = await team(client)
    parent = await start(client, agents["planner"], token_budget=2000, side_effect_budget=2)

    rejected = await delegate(client, parent["id"], "d1", "researcher", "Research", **overrides)
    replay = await delegate(client, parent["id"], "d1", "researcher", "Research", **overrides)
    detail = await get_run(client, parent["id"])

    assert rejected.status_code == replay.status_code == 409
    assert detail["steps"][0]["status"] == "rejected" and detail["steps"][0]["error_code"] == code
    assert detail["steps_used"] == 1 and detail["tokens_used"] == 0


async def test_child_budget_is_carved_out_of_the_parent(client: AsyncClient) -> None:
    agents = await team(client)
    parent = await start(client, agents["planner"], token_budget=1500)

    first = await delegate(client, parent["id"], "d1", "researcher", "Research")
    second = await delegate(client, parent["id"], "d2", "writer", "Write", token_budget=600)

    assert first.status_code == 201
    assert second.status_code == 409
    assert (await last_step(client, parent["id"]))["error_code"] == "insufficient_token_budget"


async def test_duplicate_ownership_is_rejected_until_the_first_run_is_terminal(
    client: AsyncClient,
) -> None:
    agents = await team(client)
    parent = await start(client, agents["planner"])
    first = await delegate(client, parent["id"], "d1", "researcher", "Research pricing")

    duplicate = await delegate(client, parent["id"], "d2", "writer", "  research   PRICING ")
    await act(client, await get_run(client, first.json()["step"]["child_run_id"]), "cancel")
    retried = await delegate(client, parent["id"], "d3", "writer", "Research pricing")

    assert duplicate.status_code == 409
    assert (await get_run(client, parent["id"]))["steps"][1]["error_code"] == "duplicate_ownership"
    assert retried.status_code == 201


async def test_repeated_failures_escalate_instead_of_delegating_again(
    client: AsyncClient,
) -> None:
    agents = await team(client)
    parent = await start(client, agents["planner"])
    for index in range(2):
        child = await delegate(
            client, parent["id"], f"d{index}", "researcher", f"Attempt {index}"
        )
        failed = await step(
            client,
            child.json()["step"]["child_run_id"],
            "f",
            "output",
            {"outcome": "failed", "summary": "could not do it"},
        )
        assert failed.json()["run"]["status"] == "failed"

    third = await delegate(client, parent["id"], "d3", "researcher", "Attempt 3")

    assert third.status_code == 201
    assert third.json()["step"]["error_code"] == "repeated_failure"
    assert third.json()["run"]["status"] == "waiting_human"
    assert third.json()["run"]["escalation_reason"] == "repeated_failure"
    assert third.json()["step"]["child_run_id"] is None


async def test_delegation_target_checks(client: AsyncClient) -> None:
    agents = await team(client)
    parent = await start(client, agents["planner"])
    await client.patch(
        f"{API}/agents/{agents['writer']['id']}",
        headers={**headers("user-d"), "If-Match": '"1"'},
        json={"status": "suspended"},
    )

    unknown = await delegate(client, parent["id"], "d1", "ghost", "Whatever")
    inactive = await delegate(client, parent["id"], "d2", "writer", "Write")
    quiet = await make_agent(client, "quiet", allowed_capabilities=["read"], allowed_actions=[])
    no_capability = await start(client, quiet, objective="Solo")
    denied = await step(
        client, no_capability["id"], "d", "delegate", delegation("researcher", "Research")
    )

    assert unknown.status_code == 404
    assert inactive.status_code == 409
    assert (await last_step(client, parent["id"]))["error_code"] == "target_agent_inactive"
    assert denied.json()["step"]["error_code"] == "capability_missing"
    assert denied.json()["run"]["escalation_reason"] == "policy_denial"


async def test_cancelling_a_parent_cancels_the_whole_tree(client: AsyncClient) -> None:
    agents = await team(client, max_depth=2)
    parent = await start(client, agents["planner"])
    child_id = (await delegate(client, parent["id"], "d1", "researcher", "Research")).json()[
        "step"
    ]["child_run_id"]
    grandchild = await delegate(
        client, child_id, "d2", "writer", "Write", deadline_at=deadline(0.25)
    )
    assert grandchild.status_code == 201, grandchild.text
    grandchild_id = grandchild.json()["step"]["child_run_id"]

    cancelled = await act(client, parent, "cancel")
    child = await get_run(client, child_id)
    grandchild = await get_run(client, grandchild_id)

    assert cancelled.json()["status"] == "cancelled"
    assert child["status"] == grandchild["status"] == "cancelled"
    assert child["terminal_reason"] == "parent_cancelled"
    after = await step(client, grandchild_id, "x", "output", {"summary": "late"})
    assert after.status_code == 409


async def test_sibling_conflicting_proposals_escalate_both_runs(client: AsyncClient) -> None:
    agents = await team(client)
    contact = await make_contact(client)
    parent = await start(client, agents["planner"])
    first_id = (await delegate(client, parent["id"], "d1", "researcher", "Rename A")).json()[
        "step"
    ]["child_run_id"]
    second_id = (await delegate(client, parent["id"], "d2", "writer", "Rename B")).json()["step"][
        "child_run_id"
    ]

    first = await step(client, first_id, "p", "propose", contact_update(contact, "Grace"))
    second = await step(client, second_id, "p", "propose", contact_update(contact, "Hedy"))
    proposals = await client.get(f"{API}/actions/proposals", headers=headers())
    first_run = await get_run(client, first_id)

    assert first.json()["step"]["status"] == "completed"
    assert second.json()["step"]["error_code"] == "conflicting_outputs"
    assert second.json()["run"]["status"] == "waiting_human"
    assert len(proposals.json()) == 1
    assert first_run["status"] == "waiting_human"
    assert first_run["escalation_work_item_id"] == second.json()["run"]["escalation_work_item_id"]


async def test_child_that_exhausts_its_budget_reports_to_the_parent(
    client: AsyncClient,
) -> None:
    agents = await team(client)
    parent = await start(client, agents["planner"])
    child_id = (
        await delegate(client, parent["id"], "d1", "researcher", "Research", step_budget=1)
    ).json()["step"]["child_run_id"]

    first = {"action_type": "task.create", "payload": {"title": "T"}}
    second = {"action_type": "task.create", "payload": {"title": "U"}}
    await step(client, child_id, "a", "propose", first)
    await step(client, child_id, "b", "propose", second)
    messages = await client.get(f"{API}/agent-runs/{parent['id']}/messages", headers=headers())

    assert (await get_run(client, child_id))["status"] == "budget_exhausted"
    assert [m["kind"] for m in messages.json()] == ["delegation", "result"]
    assert messages.json()[1]["body"]["status"] == "budget_exhausted"


async def test_decoy_affected_resources_cannot_hide_a_conflict(client: AsyncClient) -> None:
    agents = await team(client)
    contact = await make_contact(client)
    parent = await start(client, agents["planner"])
    first_id = (await delegate(client, parent["id"], "d1", "researcher", "Edit A")).json()[
        "step"
    ]["child_run_id"]
    second_id = (await delegate(client, parent["id"], "d2", "writer", "Edit B")).json()["step"][
        "child_run_id"
    ]
    decoy = contact_update(contact, "Hedy") | {
        "affected_resources": [{"resource_type": "decoy", "resource_id": "1"}]
    }

    await step(client, first_id, "p", "propose", contact_update(contact, "Grace"))
    second = await step(client, second_id, "p", "propose", decoy)

    assert second.json()["step"]["error_code"] == "conflicting_outputs"


async def test_cancel_reaches_an_active_grandchild_below_a_finished_child(
    client: AsyncClient,
) -> None:
    agents = await team(client, max_depth=2)
    parent = await start(client, agents["planner"])
    child_id = (await delegate(client, parent["id"], "d1", "researcher", "Research")).json()[
        "step"
    ]["child_run_id"]
    grandchild_id = (
        await delegate(
            client, child_id, "d2", "writer", "Write", deadline_at=deadline(0.25)
        )
    ).json()["step"]["child_run_id"]
    await act(client, await get_run(client, child_id), "cancel")  # child terminal, tree not
    assert (await get_run(client, grandchild_id))["status"] == "cancelled"


@pytest.mark.parametrize("how", ["output_failed", "budget"])
async def test_a_parent_that_ends_stops_its_still_running_children(
    client: AsyncClient, how: str
) -> None:
    agents = await team(client)
    parent = await start(client, agents["planner"], step_budget=2)
    child_id = (await delegate(client, parent["id"], "d1", "researcher", "Research")).json()[
        "step"
    ]["child_run_id"]

    if how == "output_failed":
        ended = await step(
            client, parent["id"], "o", "output", {"outcome": "failed", "summary": "giving up"}
        )
    else:
        await step(client, parent["id"], "a", "retrieve", {"query": "x"})
        ended = await step(client, parent["id"], "b", "retrieve", {"query": "y"})

    child = await get_run(client, child_id)
    assert ended.json()["run"]["status"] in {"failed", "budget_exhausted"}
    assert child["status"] == "cancelled" and child["terminal_reason"].startswith("parent_")
