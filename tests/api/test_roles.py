import pytest
from httpx import AsyncClient

from ai_crm.auth import create_access_token
from ai_crm.permissions import ROLE_PERMISSIONS, Permission

pytestmark = pytest.mark.asyncio


def tenant_headers(tenant_id: str, user_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-ID": tenant_id,
    }


async def test_role_matrix_is_tiered() -> None:
    admin, manager = ROLE_PERMISSIONS["admin"], ROLE_PERMISSIONS["manager"]
    member, viewer = ROLE_PERMISSIONS["member"], ROLE_PERMISSIONS["viewer"]

    assert admin == frozenset(Permission)
    assert Permission.INTEGRATIONS_MANAGE not in manager
    assert Permission.ADMIN_MEMBERS_MANAGE not in manager
    assert Permission.ACTIONS_APPROVE in manager
    assert Permission.AGENTS_MANAGE not in manager
    assert Permission.AGENTS_EVALUATE not in manager
    assert Permission.ADMIN_FLAGS_MANAGE not in manager
    assert Permission.AGENTS_RUN in member and Permission.AGENTS_RUN not in viewer
    assert Permission.AGENTS_READ in viewer
    assert viewer < member < manager < admin
    assert manager == member | {
        Permission.KNOWLEDGE_SENSITIVE,
        Permission.INTEGRATIONS_WRITE,
        Permission.ACTIONS_APPROVE,
        Permission.ACTIONS_RECOVER,
        Permission.OBSERVABILITY_MANAGE,
        Permission.ADMIN_MEMBERS_READ,
        Permission.ADMIN_FLAGS_READ,
        Permission.ADMIN_USAGE_READ,
    }
    for denied in (
        Permission.ACTIONS_APPROVE,
        Permission.ACTIONS_RECOVER,
        Permission.INTEGRATIONS_MANAGE,
        Permission.INTEGRATIONS_WRITE,
        Permission.KNOWLEDGE_SENSITIVE,
        Permission.OBSERVABILITY_MANAGE,
        Permission.ADMIN_MEMBERS_READ,
        Permission.ADMIN_MEMBERS_MANAGE,
    ):
        assert denied not in member


@pytest.mark.parametrize(
    ("user_id", "expected"),
    [("user-a", 403), ("user-b", 403), ("user-c", 403), ("user-d", 201)],
)
async def test_only_admin_can_manage_integrations(
    client: AsyncClient, user_id: str, expected: int
) -> None:
    response = await client.post(
        "/api/v1/integrations/connections",
        headers=tenant_headers("tenant-a", user_id),
        json={
            "provider_key": "fixture",
            "external_account_id": f"acct-{user_id}",
            "scopes": ["activities:read"],
            "secret_ref": "fixture-secret",
        },
    )
    assert response.status_code == expected


async def test_member_cannot_run_proactive_checks_and_denial_is_cross_tenant_safe(
    client: AsyncClient,
) -> None:
    member = await client.post(
        "/api/v1/observability/proactive-checks/run",
        headers=tenant_headers("tenant-a", "user-a"),
    )
    manager = await client.post(
        "/api/v1/observability/proactive-checks/run",
        headers=tenant_headers("tenant-a", "user-c"),
    )
    outsider = await client.post(
        "/api/v1/observability/proactive-checks/run",
        headers=tenant_headers("tenant-b", "user-c"),
    )

    assert member.status_code == 403
    assert manager.status_code == 200
    assert outsider.status_code == 403
