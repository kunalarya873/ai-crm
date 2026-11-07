import pytest
from httpx import AsyncClient

from ai_crm.auth import create_access_token

pytestmark = pytest.mark.asyncio

RESOURCES = {
    "contacts": lambda i: {"first_name": f"First{i}", "last_name": "Page"},
    "companies": lambda i: {"name": f"Company {i}"},
    "opportunities": lambda i: {"name": f"Deal {i}"},
    "tasks": lambda i: {"title": f"Task {i}"},
}


def tenant_headers(tenant_id: str, user_id: str = "user-a") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-ID": tenant_id,
    }


async def seed(client: AsyncClient, resource: str, count: int, tenant_id: str = "tenant-a"):
    ids = []
    extra: dict[str, object] = {}
    if resource == "opportunities":
        company = await client.post(
            "/api/v1/companies", headers=tenant_headers(tenant_id), json={"name": "Parent"}
        )
        extra["company_id"] = company.json()["id"]
    for index in range(count):
        response = await client.post(
            f"/api/v1/{resource}",
            headers=tenant_headers(tenant_id),
            json={**RESOURCES[resource](index), **extra},
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    return ids


async def walk(client: AsyncClient, resource: str, limit: int, tenant_id: str = "tenant-a"):
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(20):
        params: dict[str, str | int] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        response = await client.get(
            f"/api/v1/{resource}", headers=tenant_headers(tenant_id), params=params
        )
        assert response.status_code == 200
        seen.extend(item["id"] for item in response.json())
        cursor = response.headers.get("X-Next-Cursor")
        if cursor is None:
            return seen
    raise AssertionError("pagination did not terminate")


@pytest.mark.parametrize("resource", list(RESOURCES))
async def test_cursor_walk_returns_every_record_once_in_offset_order(
    client: AsyncClient, resource: str
) -> None:
    await seed(client, resource, 5)
    full = await client.get(f"/api/v1/{resource}", headers=tenant_headers("tenant-a"))

    walked = await walk(client, resource, limit=2)

    assert walked == [item["id"] for item in full.json()]
    assert len(walked) == len(set(walked)) == 5
    assert "X-Next-Cursor" not in full.headers


async def test_cursor_is_stable_when_records_are_created_between_pages(
    client: AsyncClient,
) -> None:
    await seed(client, "contacts", 4)
    first = await client.get(
        "/api/v1/contacts", headers=tenant_headers("tenant-a"), params={"limit": 2}
    )
    await seed(client, "contacts", 2)
    second = await client.get(
        "/api/v1/contacts",
        headers=tenant_headers("tenant-a"),
        params={"limit": 2, "cursor": first.headers["X-Next-Cursor"]},
    )

    first_ids = {item["id"] for item in first.json()}
    second_ids = {item["id"] for item in second.json()}
    assert len(second_ids) == 2 and not first_ids & second_ids


async def test_cursor_does_not_leak_across_tenants(client: AsyncClient) -> None:
    await seed(client, "contacts", 3)
    other_ids = await seed(client, "contacts", 3, tenant_id="tenant-b")
    page = await client.get(
        "/api/v1/contacts", headers=tenant_headers("tenant-a"), params={"limit": 2}
    )

    cross = await client.get(
        "/api/v1/contacts",
        headers=tenant_headers("tenant-b"),
        params={"limit": 50, "cursor": page.headers["X-Next-Cursor"]},
    )

    assert {item["id"] for item in cross.json()} <= set(other_ids)


async def test_invalid_cursor_and_cursor_with_offset_are_rejected(client: AsyncClient) -> None:
    await seed(client, "contacts", 3)
    headers = tenant_headers("tenant-a")
    page = await client.get("/api/v1/contacts", headers=headers, params={"limit": 2})

    garbage = await client.get("/api/v1/contacts", headers=headers, params={"cursor": "!!!"})
    wrong_shape = await client.get("/api/v1/contacts", headers=headers, params={"cursor": "e30"})
    both = await client.get(
        "/api/v1/contacts",
        headers=headers,
        params={"cursor": page.headers["X-Next-Cursor"], "offset": 1},
    )

    assert garbage.status_code == 422
    assert wrong_shape.status_code == 422
    assert both.status_code == 422


async def test_offset_pagination_still_works_and_filters_apply_with_cursor(
    client: AsyncClient,
) -> None:
    await seed(client, "tasks", 4)
    headers = tenant_headers("tenant-a")
    by_offset = await client.get("/api/v1/tasks", headers=headers, params={"limit": 2, "offset": 2})
    page = await client.get(
        "/api/v1/tasks", headers=headers, params={"limit": 2, "status": "open"}
    )
    rest = await client.get(
        "/api/v1/tasks",
        headers=headers,
        params={"limit": 5, "status": "open", "cursor": page.headers["X-Next-Cursor"]},
    )

    assert len(by_offset.json()) == 2
    assert len(page.json()) + len(rest.json()) == 4
    assert all(item["status"] == "open" for item in rest.json())


async def test_exactly_full_last_page_has_no_next_cursor(client: AsyncClient) -> None:
    await seed(client, "contacts", 3)
    headers = tenant_headers("tenant-a")

    exact = await client.get("/api/v1/contacts", headers=headers, params={"limit": 3})
    partial = await client.get("/api/v1/contacts", headers=headers, params={"limit": 2})

    assert len(exact.json()) == 3 and "X-Next-Cursor" not in exact.headers
    assert len(partial.json()) == 2 and "X-Next-Cursor" in partial.headers


async def test_naive_cursor_timestamps_are_treated_as_utc() -> None:
    import base64
    import json

    from ai_crm.pagination import decode_cursor

    raw = json.dumps({"t": "2026-01-01T00:00:00", "i": "abc"}).encode()
    created_at, item_id = decode_cursor(base64.urlsafe_b64encode(raw).decode().rstrip("="))

    assert created_at.tzinfo is not None and item_id == "abc"
