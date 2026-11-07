from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_crm.auth import create_access_token
from ai_crm.models import KnowledgeContextAssembly

pytestmark = pytest.mark.asyncio


def tenant_headers(tenant_id: str, user_id: str = "user-a") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-ID": tenant_id,
    }


async def register_and_index(
    client: AsyncClient,
    payload: dict[str, object],
    *,
    tenant_id: str = "tenant-a",
    user_id: str = "user-a",
) -> tuple[dict[str, object], dict[str, object]]:
    headers = tenant_headers(tenant_id, user_id)
    source_response = await client.post(
        "/api/v1/knowledge/sources",
        headers=headers,
        json=payload,
    )
    assert source_response.status_code == 201
    source = source_response.json()
    queued = await client.post(
        f"/api/v1/knowledge/sources/{source['id']}/index",
        headers=headers,
    )
    assert queued.status_code == 202
    job = await client.post(
        f"/api/v1/knowledge/index-jobs/{queued.json()['id']}/run",
        headers=headers,
    )
    assert job.status_code == 200
    return source, job.json()


async def test_knowledge_index_search_provenance_and_bounded_context(
    client: AsyncClient,
    tmp_path,
) -> None:
    source, job = await register_and_index(
        client,
        {
            "source_type": "document",
            "source_record_id": "doc-1",
            "title": "Acme renewal notes",
            "content": (
                "Acme renewal is planned for November. The account owner should confirm "
                "the expansion budget with the customer before the renewal meeting."
            ),
            "source_url": "https://example.test/acme-renewal",
            "customer_id": "acme",
            "effective_at": "2026-01-01T00:00:00Z",
            "fresh_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    search = await client.get(
        "/api/v1/knowledge/search",
        headers=tenant_headers("tenant-a"),
        params={"q": "renewal", "customer_id": "acme"},
    )
    context = await client.post(
        "/api/v1/knowledge/context",
        headers=tenant_headers("tenant-a"),
        json={"query": "renewal", "customer_id": "acme", "max_chars": 100},
    )
    _, _ = await register_and_index(
        client,
        {
            "source_type": "imported",
            "source_record_id": "stale-1",
            "title": "Stale renewal import",
            "content": "Stale renewal evidence should be labelled and filterable.",
            "fresh_until": "2020-01-01T00:00:00Z",
        },
    )
    stale_visible = await client.get(
        "/api/v1/knowledge/search",
        headers=tenant_headers("tenant-a"),
        params={"q": "stale"},
    )
    stale_filtered = await client.get(
        "/api/v1/knowledge/search",
        headers=tenant_headers("tenant-a"),
        params={"q": "stale", "include_stale": False},
    )

    assert job["status"] == "succeeded"
    assert job["indexed_chunks"] == 1
    assert search.status_code == 200
    result = search.json()
    assert result["insufficient_evidence"] is False
    assert result["items"][0]["source_id"] == source["id"]
    assert result["items"][0]["citation"]["source_record_id"] == "doc-1"
    assert result["items"][0]["citation"]["fresh_until"] is not None
    assert result["items"][0]["freshness"] == "fresh"
    assert stale_visible.json()["items"][0]["freshness"] == "stale"
    assert stale_filtered.json()["items"] == []
    assert context.status_code == 200
    context_result = context.json()
    assert context_result["assembly_id"]
    assert context_result["used_chars"] <= 100
    assert context_result["truncated"] is True

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        assembly = await session.scalar(
            select(KnowledgeContextAssembly).where(
                KnowledgeContextAssembly.id == context_result["assembly_id"]
            )
        )
    await engine.dispose()
    assert assembly is not None
    assert assembly.item_ids
    assert assembly.citations[0]["source_id"] == source["id"]


async def test_knowledge_index_replay_update_and_failure_are_visible(client: AsyncClient) -> None:
    source, _ = await register_and_index(
        client,
        {
            "source_type": "procedure",
            "source_record_id": "procedure-1",
            "title": "Renewal procedure",
            "content": "Use the renewal checklist before the customer meeting.",
        },
    )
    headers = tenant_headers("tenant-a")
    first_queue = await client.post(
        f"/api/v1/knowledge/sources/{source['id']}/index",
        headers=headers,
    )
    second_queue = await client.post(
        f"/api/v1/knowledge/sources/{source['id']}/index",
        headers=headers,
    )
    updated = await client.patch(
        f"/api/v1/knowledge/sources/{source['id']}",
        headers={**headers, "If-Match": '"1"'},
        json={
            "title": "Expansion procedure",
            "content": "Use the expansion checklist before the customer meeting.",
        },
    )
    updated_job = await client.post(
        f"/api/v1/knowledge/sources/{source['id']}/index",
        headers=headers,
    )
    updated_run = await client.post(
        f"/api/v1/knowledge/index-jobs/{updated_job.json()['id']}/run",
        headers=headers,
    )
    old_search = await client.get(
        "/api/v1/knowledge/search",
        headers=headers,
        params={"q": "renewal"},
    )
    new_search = await client.get(
        "/api/v1/knowledge/search",
        headers=headers,
        params={"q": "expansion"},
    )
    archived = await client.patch(
        f"/api/v1/knowledge/sources/{source['id']}",
        headers={**headers, "If-Match": '"2"'},
        json={"archived": True},
    )
    archived_job = await client.post(
        f"/api/v1/knowledge/sources/{source['id']}/index",
        headers=headers,
    )
    archived_run = await client.post(
        f"/api/v1/knowledge/index-jobs/{archived_job.json()['id']}/run",
        headers=headers,
    )
    archived_search = await client.get(
        "/api/v1/knowledge/search",
        headers=headers,
        params={"q": "expansion"},
    )

    failed_source, _ = await register_and_index(
        client,
        {
            "source_type": "imported",
            "source_record_id": "empty-1",
            "title": "Empty import",
            "content": "initial content",
        },
    )
    failed_update = await client.patch(
        f"/api/v1/knowledge/sources/{failed_source['id']}",
        headers={**headers, "If-Match": '"1"'},
        json={"content": "   "},
    )
    failed_queue = await client.post(
        f"/api/v1/knowledge/sources/{failed_source['id']}/index",
        headers=headers,
    )
    failed_run = await client.post(
        f"/api/v1/knowledge/index-jobs/{failed_queue.json()['id']}/run",
        headers=headers,
    )

    assert first_queue.status_code == 202
    assert second_queue.status_code == 202
    assert first_queue.json()["id"] == second_queue.json()["id"]
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated_run.json()["status"] == "succeeded"
    assert old_search.json()["items"] == []
    assert new_search.json()["items"]
    assert archived.status_code == 200
    assert archived_run.json()["indexed_chunks"] == 0
    assert archived_search.json()["items"] == []
    assert failed_update.status_code == 200
    assert failed_run.json()["status"] == "failed"
    assert failed_run.json()["failure_code"] == "indexing_failed"


async def test_knowledge_visibility_and_tenant_filters_do_not_leak_metadata(
    client: AsyncClient,
) -> None:
    private_source, _ = await register_and_index(
        client,
        {
            "source_type": "document",
            "source_record_id": "private-1",
            "title": "Private customer note",
            "content": "private phrase only for the owner",
            "visibility": "owner",
        },
    )
    restricted_source, _ = await register_and_index(
        client,
        {
            "source_type": "document",
            "source_record_id": "restricted-1",
            "title": "Restricted customer note",
            "content": "restricted phrase only for selected users",
            "visibility": "restricted",
            "allowed_user_ids": ["user-a"],
        },
    )
    sensitive_source, _ = await register_and_index(
        client,
        {
            "source_type": "document",
            "source_record_id": "sensitive-1",
            "title": "Sensitive customer note",
            "content": "sensitive phrase with private details",
            "sensitivity": "sensitive",
        },
    )

    viewer_headers = tenant_headers("tenant-a", "user-b")
    viewer_private = await client.get(
        f"/api/v1/knowledge/sources/{private_source['id']}",
        headers=viewer_headers,
    )
    viewer_search = await client.get(
        "/api/v1/knowledge/search",
        headers=viewer_headers,
        params={"q": "phrase"},
    )
    viewer_context = await client.post(
        "/api/v1/knowledge/context",
        headers=viewer_headers,
        json={"query": "sensitive phrase"},
    )
    other_tenant_search = await client.get(
        "/api/v1/knowledge/search",
        headers=tenant_headers("tenant-b"),
        params={"q": "phrase"},
    )
    owner_search = await client.get(
        "/api/v1/knowledge/search",
        headers=tenant_headers("tenant-a"),
        params={"q": "phrase"},
    )

    assert viewer_private.status_code == 404
    assert viewer_search.status_code == 200
    assert all(
        item["source_id"] not in {
            private_source["id"],
            restricted_source["id"],
            sensitive_source["id"],
        }
        for item in viewer_search.json()["items"]
    )
    assert other_tenant_search.json()["items"] == []
    assert viewer_context.status_code == 200
    assert viewer_context.json()["items"] == []
    assert viewer_context.json()["insufficient_evidence"] is True
    owner_ids = {item["source_id"] for item in owner_search.json()["items"]}
    assert {private_source["id"], restricted_source["id"]} <= owner_ids
    assert sensitive_source["id"] not in owner_ids
    sensitive_search = await client.get(
        "/api/v1/knowledge/search",
        headers=tenant_headers("tenant-a", "user-d"),
        params={"q": "phrase"},
    )
    assert sensitive_source["id"] in {
        item["source_id"] for item in sensitive_search.json()["items"]
    }


async def test_context_excludes_non_ai_sources_and_reports_insufficient_evidence(
    client: AsyncClient,
) -> None:
    source, _ = await register_and_index(
        client,
        {
            "source_type": "template",
            "source_record_id": "template-1",
            "title": "Internal template",
            "content": "internal template phrase",
            "ai_allowed": False,
        },
    )
    search = await client.get(
        "/api/v1/knowledge/search",
        headers=tenant_headers("tenant-a"),
        params={"q": "template phrase"},
    )
    context = await client.post(
        "/api/v1/knowledge/context",
        headers=tenant_headers("tenant-a"),
        json={"query": "template phrase"},
    )

    assert search.status_code == 200
    assert search.json()["items"][0]["source_id"] == source["id"]
    assert context.status_code == 200
    assert context.json()["items"] == []
    assert context.json()["insufficient_evidence"] is True
