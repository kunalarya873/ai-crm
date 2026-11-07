from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_crm.agents.eval import SCENARIOS
from ai_crm.models import ActionExecution, ActionProposal
from tests.api.agent_helpers import API, headers

pytestmark = pytest.mark.asyncio

Factory = async_sessionmaker[AsyncSession]
ADMIN = "user-d"


async def run_eval(
    client: AsyncClient, replay_key: str = "r1", scenario_key: str | None = None, **kw: Any
):
    body: dict[str, Any] = {"replay_key": replay_key}
    if scenario_key:
        body["scenario_key"] = scenario_key
    return await client.post(
        f"{API}/agent-evals/run",
        headers=headers(kw.get("user", ADMIN), kw.get("tenant", "tenant-a")),
        json=body,
    )


def by_key(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["scenario_key"]: item["strategies"] for item in report["comparisons"]}


async def test_every_scenario_meets_its_expectation_for_both_strategies_or_documents_why(
    client: AsyncClient,
) -> None:
    response = await run_eval(client)
    results = by_key(response.json())

    assert response.status_code == 200
    assert set(results) == set(SCENARIOS)
    for key in ("parallel_research", "partial_failure", "duplicate_work", "budget_pressure"):
        assert results[key]["single_agent"]["task_success"] is True, key
        assert results[key]["multi_agent"]["task_success"] is True, key
    # Cross-run conflict detection is where coordination adds value over one agent.
    assert results["conflicting_data"]["multi_agent"]["task_success"] is True
    assert results["conflicting_data"]["single_agent"]["task_success"] is False


async def test_metrics_are_hand_checkable(client: AsyncClient) -> None:
    results = by_key((await run_eval(client)).json())

    parallel = results["parallel_research"]
    assert parallel["single_agent"]["steps"] == 3
    assert parallel["multi_agent"]["steps"] == 7
    assert parallel["multi_agent"]["runs"] == 3 and parallel["single_agent"]["runs"] == 1
    assert parallel["multi_agent"]["handoffs"] == 2
    assert parallel["multi_agent"]["handoff_latency_ms"] >= 0
    assert parallel["single_agent"]["handoff_latency_ms"] is None
    assert parallel["single_agent"]["tokens"] == 210
    assert parallel["multi_agent"]["tokens"] == 330

    duplicate = results["duplicate_work"]
    assert duplicate["single_agent"]["duplicate_work"] == 1
    assert duplicate["multi_agent"]["duplicate_work"] == 1
    assert duplicate["multi_agent"]["failed_tool_calls"] == 1

    conflict = results["conflicting_data"]["multi_agent"]
    assert conflict["human_interventions"] == 1
    assert conflict["escalation_reasons"] == ["conflicting_outputs"]
    assert conflict["proposals"] == 1
    assert results["conflicting_data"]["single_agent"]["proposals"] == 2

    budget = results["budget_pressure"]
    assert budget["single_agent"]["root_status"] == "budget_exhausted"
    assert budget["multi_agent"]["root_status"] == "completed"
    assert budget["single_agent"]["human_interventions"] == 1

    failure = results["partial_failure"]
    assert failure["single_agent"]["failed_tool_calls"] == 1
    assert failure["multi_agent"]["proposals"] == 1


async def test_replays_are_deterministic_and_idempotent(client: AsyncClient) -> None:
    first = by_key((await run_eval(client, "same")).json())
    again = by_key((await run_eval(client, "same")).json())
    other = by_key((await run_eval(client, "other")).json())
    results = await client.get(f"{API}/agent-evals/results", headers=headers(ADMIN))

    def stable(values: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {
            key: {
                strategy: {k: v for k, v in metrics.items() if k != "handoff_latency_ms"}
                for strategy, metrics in strategies.items()
            }
            for key, strategies in values.items()
        }

    assert stable(first) == stable(again) == stable(other)
    assert first["parallel_research"]["multi_agent"]["handoff_latency_ms"] == (
        again["parallel_research"]["multi_agent"]["handoff_latency_ms"]
    )
    assert len(results.json()) == len(SCENARIOS) * 2 * 2  # "same" stored once, plus "other"


async def test_comparison_always_carries_assumptions_and_labels_the_baseline(
    client: AsyncClient,
) -> None:
    report = (await run_eval(client, "r1", "conflicting_data")).json()
    compare = await client.get(
        f"{API}/agent-evals/compare",
        headers=headers("user-b"),
        params={"scenario_key": "conflicting_data"},
    )
    body = compare.json()

    assert len(report["comparisons"]) == 1
    assert report["assumptions"] and body["assumptions"]
    assert body["strategies"]["human_baseline"]["assumption"] is True
    assert body["strategies"]["human_baseline"]["minutes"] == 30
    assert "deltas_multi_minus_single" in body
    assert report["aggregate"]["multi_agent"] == {
        "scenarios": 1,
        "successes": 1,
        "steps": body["strategies"]["multi_agent"]["steps"],
        "tokens": body["strategies"]["multi_agent"]["tokens"],
        "human_interventions": 1,
    }


async def test_evaluation_never_approves_or_executes(
    client: AsyncClient, session_factory: Factory
) -> None:
    await run_eval(client)
    async with session_factory() as session:
        proposals = list(await session.scalars(select(ActionProposal)))
        executions = list(await session.scalars(select(ActionExecution)))

    assert proposals and all(p.status == "proposed" for p in proposals)
    assert executions == []


@pytest.mark.parametrize("user_id", ["user-a", "user-b", "user-c"])
async def test_only_admin_can_run_evaluations(client: AsyncClient, user_id: str) -> None:
    denied = await run_eval(client, user=user_id)

    assert denied.status_code == 403


async def test_read_access_and_validation(client: AsyncClient) -> None:
    await run_eval(client, "r1", "duplicate_work")
    scenarios = await client.get(f"{API}/agent-evals/scenarios", headers=headers("user-b"))
    unknown = await run_eval(client, "r1", "nope")
    missing = await client.get(
        f"{API}/agent-evals/compare",
        headers=headers(ADMIN),
        params={"scenario_key": "budget_pressure"},
    )
    blank = await client.post(
        f"{API}/agent-evals/run", headers=headers(ADMIN), json={"replay_key": ""}
    )

    assert len(scenarios.json()) == len(SCENARIOS)
    assert all(item["human_baseline_is_assumption"] for item in scenarios.json())
    assert unknown.status_code == 404
    assert missing.status_code == 404
    assert blank.status_code == 422


async def test_results_are_tenant_isolated(client: AsyncClient) -> None:
    await run_eval(client, "r1", "duplicate_work")
    await run_eval(client, "r1", "budget_pressure", tenant="tenant-b")

    a = await client.get(f"{API}/agent-evals/results", headers=headers(ADMIN, "tenant-a"))
    b = await client.get(f"{API}/agent-evals/results", headers=headers(ADMIN, "tenant-b"))
    cross = await client.get(
        f"{API}/agent-evals/compare",
        headers=headers(ADMIN, "tenant-b"),
        params={"scenario_key": "duplicate_work"},
    )

    assert {r["scenario_key"] for r in a.json()} == {"duplicate_work"}
    assert {r["scenario_key"] for r in b.json()} == {"budget_pressure"}
    assert cross.status_code == 404
