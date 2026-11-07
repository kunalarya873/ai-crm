from typing import Any

import pytest
from httpx import AsyncClient

from ai_crm.auth import create_access_token

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/admin/members"


def tenant_headers(tenant_id: str, user_id: str = "user-d") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-ID": tenant_id,
    }


async def members(client: AsyncClient, tenant_id: str = "tenant-a") -> dict[str, dict[str, Any]]:
    response = await client.get(BASE, headers=tenant_headers(tenant_id))
    assert response.status_code == 200
    return {item["user_id"]: item for item in response.json()}


async def patch(
    client: AsyncClient,
    member: dict[str, Any],
    body: dict[str, Any],
    *,
    user_id: str = "user-d",
    tenant_id: str = "tenant-a",
    version: object | None = None,
):
    headers = tenant_headers(tenant_id, user_id)
    headers["If-Match"] = f'"{member["version"] if version is None else version}"'
    return await client.patch(f"{BASE}/{member['id']}", headers=headers, json=body)


async def test_list_is_tenant_scoped_and_readable_by_admin_and_manager(
    client: AsyncClient,
) -> None:
    tenant_a = await members(client)
    tenant_b = await members(client, "tenant-b")
    manager_view = await client.get(BASE, headers=tenant_headers("tenant-a", "user-c"))

    assert set(tenant_a) == {"user-a", "user-b", "user-c", "user-d"}
    assert set(tenant_b) == {"user-a", "user-d"}
    assert tenant_a["user-d"]["email"] == "user-d@example.com"
    assert manager_view.status_code == 200


@pytest.mark.parametrize("user_id", ["user-a", "user-b"])
async def test_member_and_viewer_cannot_read_or_write(
    client: AsyncClient, user_id: str
) -> None:
    headers = tenant_headers("tenant-a", user_id)

    read = await client.get(BASE, headers=headers)
    write = await client.post(BASE, headers=headers, json={"email": "x@y.z", "role": "viewer"})

    assert read.status_code == 403 and write.status_code == 403


async def test_manager_can_read_but_not_manage(client: AsyncClient) -> None:
    current = await members(client)
    headers = tenant_headers("tenant-a", "user-c")

    add = await client.post(
        BASE, headers=headers, json={"email": "user-e@example.com", "role": "viewer"}
    )
    change = await patch(client, current["user-a"], {"role": "viewer"}, user_id="user-c")

    assert add.status_code == 403 and change.status_code == 403


async def test_add_member_validations(client: AsyncClient) -> None:
    headers = tenant_headers("tenant-a")

    created = await client.post(
        BASE, headers=headers, json={"email": " User-E@Example.com ", "role": "viewer"}
    )
    duplicate = await client.post(
        BASE, headers=headers, json={"email": "user-e@example.com", "role": "viewer"}
    )
    unknown = await client.post(
        BASE, headers=headers, json={"email": "nobody@example.com", "role": "viewer"}
    )
    bad_role = await client.post(
        BASE, headers=headers, json={"email": "user-e@example.com", "role": "owner"}
    )
    extra = await client.post(
        BASE, headers=headers, json={"email": "user-e@example.com", "role": "viewer", "x": 1}
    )

    assert created.status_code == 201
    assert created.json()["user_id"] == "user-e" and created.json()["version"] == 1
    assert created.headers["etag"] == '"1"'
    assert duplicate.status_code == 409
    assert unknown.status_code == 404
    assert bad_role.status_code == 422 and extra.status_code == 422
    assert "user-e" in await members(client)
    assert "user-e" not in await members(client, "tenant-b")


async def test_patch_requires_current_version_and_bumps_it(client: AsyncClient) -> None:
    viewer = (await members(client))["user-b"]
    headers = tenant_headers("tenant-a")

    missing = await client.patch(f"{BASE}/{viewer['id']}", headers=headers, json={"role": "member"})
    stale = await patch(client, viewer, {"role": "member"}, version=7)
    empty = await patch(client, viewer, {})
    changed = await patch(client, viewer, {"role": "member"})
    stale_again = await patch(client, viewer, {"role": "manager"})

    assert missing.status_code == 428
    assert stale.status_code == 409
    assert empty.status_code == 422
    assert changed.status_code == 200
    assert changed.json()["role"] == "member" and changed.json()["version"] == 2
    assert changed.headers["etag"] == '"2"'
    assert stale_again.status_code == 409


async def test_last_active_admin_cannot_be_demoted_or_deactivated(client: AsyncClient) -> None:
    current = await members(client)
    admin = current["user-d"]

    demote = await patch(client, admin, {"role": "manager"})
    deactivate = await patch(client, admin, {"is_active": False})
    promote = await patch(client, current["user-c"], {"role": "admin"})
    demote_after = await patch(client, admin, {"role": "manager"}, user_id="user-d")

    assert demote.status_code == 409 and deactivate.status_code == 409
    assert promote.status_code == 200
    assert demote_after.status_code == 200
    assert (await members(client))["user-d"]["role"] == "manager"


async def test_role_changes_and_deactivation_take_effect_immediately(
    client: AsyncClient,
) -> None:
    current = await members(client)
    task = {"title": "Needs write access"}
    viewer_headers = tenant_headers("tenant-a", "user-b")

    before = await client.post("/api/v1/tasks", headers=viewer_headers, json=task)
    await patch(client, current["user-b"], {"role": "member"})
    after = await client.post("/api/v1/tasks", headers=viewer_headers, json=task)

    member = (await members(client))["user-a"]
    deactivated = await patch(client, member, {"is_active": False})
    blocked = await client.get("/api/v1/tasks", headers=tenant_headers("tenant-a", "user-a"))
    other_tenant = await client.get("/api/v1/tasks", headers=tenant_headers("tenant-b", "user-a"))
    reactivated = await patch(client, deactivated.json(), {"is_active": True})
    restored = await client.get("/api/v1/tasks", headers=tenant_headers("tenant-a", "user-a"))

    assert before.status_code == 403 and after.status_code == 201
    assert deactivated.status_code == 200 and blocked.status_code == 403
    assert other_tenant.status_code == 200
    assert reactivated.status_code == 200 and restored.status_code == 200


async def test_membership_ids_do_not_cross_tenants(client: AsyncClient) -> None:
    tenant_a_member = (await members(client))["user-a"]

    response = await patch(
        client, tenant_a_member, {"role": "viewer"}, user_id="user-d", tenant_id="tenant-b"
    )

    assert response.status_code == 404
    assert (await members(client))["user-a"]["role"] == "member"


async def test_seeded_demo_identities_allow_propose_and_approve_flow(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select

    from ai_crm.db import _seed_identity
    from ai_crm.models import Membership

    async with session_factory() as session:
        await _seed_identity(session)
        await _seed_identity(session)  # idempotent
        rows = (
            await session.scalars(select(Membership).where(Membership.tenant_id == "demo-tenant"))
        ).all()

    assert {(m.user_id, m.role) for m in rows} == {
        ("demo-user", "admin"),
        ("demo-manager", "manager"),
    }


async def test_concurrent_duplicate_add_returns_conflict_not_500(client: AsyncClient) -> None:
    import asyncio

    body = {"email": "user-e@example.com", "role": "viewer"}
    results = await asyncio.gather(
        client.post(BASE, headers=tenant_headers("tenant-a"), json=body),
        client.post(BASE, headers=tenant_headers("tenant-a"), json=body),
    )

    assert sorted(r.status_code for r in results) == [201, 409]


async def test_inactive_admin_is_not_counted_by_the_last_admin_guard(
    client: AsyncClient, session_factory
) -> None:
    from sqlalchemy import update

    from ai_crm.models import User

    current = await members(client)
    await patch(client, current["user-c"], {"role": "admin"})
    async with session_factory() as session:
        await session.execute(update(User).where(User.id == "user-c").values(is_active=False))
        await session.commit()
    refreshed = await members(client)

    inactive_admin = await patch(client, refreshed["user-c"], {"role": "viewer"})
    last_active_admin = await patch(client, refreshed["user-d"], {"role": "viewer"})

    assert inactive_admin.status_code == 200
    assert last_active_admin.status_code == 409


async def test_concurrent_patches_with_the_same_version_only_one_wins(
    client: AsyncClient,
) -> None:
    import asyncio

    viewer = (await members(client))["user-b"]

    results = await asyncio.gather(
        patch(client, viewer, {"role": "member"}),
        patch(client, viewer, {"role": "manager"}),
    )

    assert sorted(r.status_code for r in results) == [200, 409]
    assert (await members(client))["user-b"]["version"] == 2
