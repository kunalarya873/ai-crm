from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_crm.config import settings
from ai_crm.models import (
    AuditEvent,
    Contact,
    MetricObservation,
    OperationalAlert,
    OperationalEvent,
    OutboxEvent,
)
from tests.api.agent_helpers import API, headers

Factory = async_sessionmaker[AsyncSession]
OLD = datetime.now(UTC) - timedelta(days=400)


async def make_contacts(client: AsyncClient, count: int, tenant: str = "tenant-a") -> list[str]:
    ids = []
    for index in range(count):
        response = await client.post(
            f"{API}/contacts",
            headers=headers("user-d", tenant),
            json={"first_name": f"First{index}", "last_name": "Last"},
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    return ids


# --- audit investigation ---------------------------------------------------------------------


async def test_audit_query_filters_and_is_itself_audited(client: AsyncClient) -> None:
    await make_contacts(client, 2)

    response = await client.get(
        f"{API}/admin/audit-events",
        headers=headers("user-d"),
        params={"entity_type": "contact", "actor_id": "user-d"},
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2 and {row["entity_type"] for row in rows} == {"contact"}
    assert [row["id"] for row in rows] == sorted((row["id"] for row in rows), reverse=True)
    follow_up = await client.get(
        f"{API}/admin/audit-events", headers=headers("user-d"), params={"action": "audit.queried"}
    )
    assert follow_up.json()[0]["details"]["filters"] == {
        "entity_type": "contact",
        "actor_id": "user-d",
    }


async def test_audit_query_paginates_without_gaps(client: AsyncClient) -> None:
    await make_contacts(client, 5)
    seen: list[int] = []
    cursor = None
    for _ in range(10):
        params: dict[str, str | int] = {"limit": 2, "entity_type": "contact"}
        if cursor:
            params["cursor"] = cursor
        response = await client.get(
            f"{API}/admin/audit-events", headers=headers("user-d"), params=params
        )
        seen += [row["id"] for row in response.json()]
        cursor = response.headers.get("X-Next-Cursor")
        if cursor is None:
            break
    assert len(seen) == 5 and len(set(seen)) == 5


async def test_audit_query_validation_and_isolation(client: AsyncClient) -> None:
    await make_contacts(client, 1)
    bad_cursor = await client.get(
        f"{API}/admin/audit-events", headers=headers("user-d"), params={"cursor": "abc"}
    )
    reversed_range = await client.get(
        f"{API}/admin/audit-events",
        headers=headers("user-d"),
        params={"since": "2030-01-02T00:00:00Z", "until": "2030-01-01T00:00:00Z"},
    )
    other = await client.get(
        f"{API}/admin/audit-events",
        headers=headers("user-d", "tenant-b"),
        params={"entity_type": "contact"},
    )

    assert bad_cursor.status_code == 422 and reversed_range.status_code == 422
    assert other.json() == []


@pytest.mark.parametrize("user", ["user-a", "user-b", "user-c"])
async def test_non_admins_cannot_use_lifecycle_endpoints(client: AsyncClient, user: str) -> None:
    h = headers(user)
    assert (await client.get(f"{API}/admin/audit-events", headers=h)).status_code == 403
    assert (await client.get(f"{API}/admin/export/contacts", headers=h)).status_code == 403
    purge = await client.post(f"{API}/admin/retention/purge", headers=h, json={})
    assert purge.status_code == 403


# --- export ----------------------------------------------------------------------------------


async def test_export_pages_cover_every_row_once_and_include_archived(
    client: AsyncClient, session_factory: Factory
) -> None:
    ids = await make_contacts(client, 5)
    async with session_factory() as session:
        contact = await session.get(Contact, ids[0])
        assert contact is not None
        contact.archived_at = datetime.now(UTC)
        await session.commit()

    exported: list[str] = []
    cursor = None
    for _ in range(10):
        params: dict[str, str | int] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = await client.get(
            f"{API}/admin/export/contacts", headers=headers("user-d"), params=params
        )
        assert response.status_code == 200
        exported += [row["id"] for row in response.json()]
        cursor = response.headers.get("X-Next-Cursor")
        if cursor is None:
            break

    assert sorted(exported) == sorted(ids)
    audit = await client.get(
        f"{API}/admin/audit-events", headers=headers("user-d"), params={"action": "export.read"}
    )
    assert len(audit.json()) == 3


async def test_export_is_tenant_isolated_and_resource_allowlisted(client: AsyncClient) -> None:
    await make_contacts(client, 2)
    other = await client.get(f"{API}/admin/export/contacts", headers=headers("user-d", "tenant-b"))
    unknown = await client.get(
        f"{API}/admin/export/integration_connections", headers=headers("user-d")
    )
    for resource in ("companies", "opportunities", "activities", "tasks"):
        empty = await client.get(f"{API}/admin/export/{resource}", headers=headers("user-d"))
        assert empty.status_code == 200 and empty.json() == []

    assert other.json() == []
    assert unknown.status_code == 404


# --- retention purge -------------------------------------------------------------------------


async def seed_telemetry(factory: Factory, tenant: str = "tenant-a") -> None:
    async with factory() as session:
        session.add_all(
            [
                OperationalEvent(
                    tenant_id=tenant,
                    actor_id="u",
                    event_type=f"t.{label}",
                    operation="op",
                    resource_type="r",
                    resource_id="1",
                    outcome="success",
                    correlation_id="c",
                    dedup_key=f"{label}-{tenant}",
                    created_at=when,
                )
                for label, when in (("old", OLD), ("new", datetime.now(UTC)))
            ]
        )
        session.add_all(
            [
                MetricObservation(
                    tenant_id=tenant,
                    metric_key="m",
                    value=1.0,
                    unit="count",
                    dimensions={},
                    window_start=when,
                    window_end=when,
                    created_at=when,
                )
                for when in (OLD, datetime.now(UTC))
            ]
        )
        session.add_all(
            [
                OperationalAlert(
                    tenant_id=tenant,
                    alert_type="a",
                    rule_key="r",
                    dedup_key=f"{status}-{index}-{tenant}",
                    severity="low",
                    status=status,
                    title="t",
                    description="d",
                    resolved_at=resolved,
                    created_at=OLD,
                )
                for index, (status, resolved) in enumerate(
                    (("resolved", OLD), ("resolved", datetime.now(UTC)), ("open", None))
                )
            ]
        )
        session.add_all(
            [
                OutboxEvent(
                    tenant_id=tenant,
                    event_type="e",
                    aggregate_type="a",
                    aggregate_id=label,
                    correlation_id="c",
                    payload={},
                    created_at=OLD,
                    published_at=published,
                )
                for label, published in (
                    ("old", OLD),
                    ("recent", datetime.now(UTC)),
                    ("pending", None),
                )
            ]
        )
        await session.commit()


async def table_counts(factory: Factory, tenant: str = "tenant-a") -> dict[str, int]:
    async with factory() as session:
        result = {}
        for name, model in (
            ("events", OperationalEvent),
            ("metrics", MetricObservation),
            ("alerts", OperationalAlert),
            ("outbox", OutboxEvent),
            ("contacts", Contact),
        ):
            result[name] = int(
                await session.scalar(
                    select(func.count()).select_from(model).where(model.tenant_id == tenant)
                )
                or 0
            )
        return result


async def purge(client: AsyncClient, tenant: str = "tenant-a", **body):
    return await client.post(
        f"{API}/admin/retention/purge", headers=headers("user-d", tenant), json=body
    )


async def test_purge_dry_run_is_default_and_deletes_nothing(
    client: AsyncClient, session_factory: Factory
) -> None:
    await seed_telemetry(session_factory)
    before = await table_counts(session_factory)

    response = await purge(client)

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["older_than_days"] == settings.observability_retention_days
    assert body["counts"] == {
        "operational_events": 1,
        "metric_observations": 1,
        "resolved_alerts": 1,
        "published_outbox_events": 1,
    }
    assert await table_counts(session_factory) == before


async def test_purge_deletes_only_aged_telemetry_and_is_audited(
    client: AsyncClient, session_factory: Factory
) -> None:
    await make_contacts(client, 1)
    await seed_telemetry(session_factory)
    await seed_telemetry(session_factory, "tenant-b")
    other_before = await table_counts(session_factory, "tenant-b")
    async with session_factory() as session:
        audit_before = int(await session.scalar(select(func.count()).select_from(AuditEvent)) or 0)

    response = await purge(client, dry_run=False)

    body = response.json()
    assert sum(body["counts"].values()) == 4 and body["truncated"] is False
    after = await table_counts(session_factory)
    assert after["contacts"] == 1
    assert after["alerts"] == 2  # the recently resolved and the open alert survive
    assert after["outbox"] >= 2  # recent and pending rows survive
    assert await table_counts(session_factory, "tenant-b") == other_before
    async with session_factory() as session:
        audit_after = int(await session.scalar(select(func.count()).select_from(AuditEvent)) or 0)
    assert audit_after >= audit_before  # audit events are never purged
    audit = await client.get(
        f"{API}/admin/audit-events",
        headers=headers("user-d"),
        params={"action": "retention.purged"},
    )
    assert audit.json()[0]["details"]["counts"] == body["counts"]

    again = (await purge(client, dry_run=False)).json()
    assert sum(again["counts"].values()) == 0


async def test_purge_rejects_cutoff_below_the_configured_retention(client: AsyncClient) -> None:
    too_recent = await purge(client, older_than_days=settings.observability_retention_days - 1)
    invalid = await purge(client, older_than_days=0)
    extra = await purge(client, surprise=True)

    assert too_recent.status_code == 422 and invalid.status_code == 422
    assert extra.status_code == 422


async def test_purge_batch_cap_limits_each_call(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "retention_purge_batch_size", 1)
    async with session_factory() as session:
        session.add_all(
            [
                MetricObservation(
                    tenant_id="tenant-a",
                    metric_key="m",
                    value=float(index),
                    unit="count",
                    dimensions={},
                    window_start=OLD,
                    window_end=OLD,
                    created_at=OLD,
                )
                for index in range(3)
            ]
        )
        await session.commit()

    first = (await purge(client, dry_run=False)).json()
    assert first["counts"]["metric_observations"] == 1 and first["truncated"] is True
    await purge(client, dry_run=False)
    last = (await purge(client, dry_run=False)).json()

    assert last["counts"]["metric_observations"] == 1 and last["truncated"] is False
    assert (await table_counts(session_factory))["metrics"] == 0


async def test_purge_reports_truncated_only_when_rows_remain(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "retention_purge_batch_size", 2)
    await seed_telemetry(session_factory)

    body = (await purge(client, dry_run=False)).json()

    assert sum(body["counts"].values()) == 4 and body["truncated"] is False


async def test_export_audit_rows_do_not_pollute_entity_filters(client: AsyncClient) -> None:
    ids = await make_contacts(client, 1)
    await client.get(f"{API}/admin/export/contacts", headers=headers("user-d"))

    rows = (
        await client.get(
            f"{API}/admin/audit-events",
            headers=headers("user-d"),
            params={"entity_type": "contacts"},
        )
    ).json()
    export = (
        await client.get(
            f"{API}/admin/audit-events",
            headers=headers("user-d"),
            params={"entity_type": "export", "entity_id": "contacts"},
        )
    ).json()

    assert rows == [] and len(export) == 1 and ids


async def test_audit_query_accepts_naive_timestamps_as_utc(client: AsyncClient) -> None:
    await make_contacts(client, 1)

    response = await client.get(
        f"{API}/admin/audit-events",
        headers=headers("user-d"),
        params={"since": "2000-01-01T00:00:00", "until": "2100-01-01T00:00:00"},
    )

    assert response.status_code == 200 and len(response.json()) >= 1
