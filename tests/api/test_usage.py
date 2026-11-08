from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_crm.models import DurableJob
from tests.api.agent_helpers import API, act, headers, make_agent, start

Factory = async_sessionmaker[AsyncSession]


async def usage(client: AsyncClient, user: str = "user-d", tenant: str = "tenant-a"):
    return await client.get(f"{API}/admin/usage", headers=headers(user, tenant))


async def test_usage_counts_match_the_tenant(client: AsyncClient, session_factory: Factory) -> None:
    agent = await make_agent(client, "planner")
    running = await start(client, agent, objective="one")
    cancelled = await start(client, agent, objective="two")
    await act(client, cancelled, "cancel")
    await client.put(
        f"{API}/admin/feature-flags/ai",
        headers={**headers("user-d"), "If-Match": '"0"'},
        json={"enabled": False, "reason": "incident"},
    )
    async with session_factory() as session:
        session.add(
            DurableJob(
                tenant_id="tenant-a",
                idempotency_key="j",
                request_hash="h",
                job_type="notification.send",
                status="dead_letter",
                run_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await session.commit()

    body = (await usage(client)).json()

    assert body["members_by_role"] == {"admin": 1, "manager": 1, "member": 1, "viewer": 1}
    assert body["agent_runs_by_status"] == {"running": 1, "cancelled": 1}
    assert body["jobs_by_status"] == {"dead_letter": 1}
    assert body["ai_runs"] == {
        "runs": 0,
        "fallbacks": 0,
        "estimated_cost_micros": 0,
        "total_tokens": 0,
    }
    ai = next(item for item in body["capabilities"] if item["flag"] == "ai")
    assert ai["enabled"] is False and running["status"] == "running"


async def test_usage_is_tenant_isolated_and_permissioned(client: AsyncClient) -> None:
    agent = await make_agent(client, "planner")
    await start(client, agent)

    other = (await usage(client, "user-d", "tenant-b")).json()
    manager = await usage(client, "user-c")
    member = await usage(client, "user-a")
    viewer = await usage(client, "user-b")

    assert other["members_by_role"] == {"admin": 1, "member": 1}
    assert other["agent_runs_by_status"] == {}
    assert manager.status_code == 200
    assert member.status_code == 403 and viewer.status_code == 403
