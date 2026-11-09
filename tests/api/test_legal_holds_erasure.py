import asyncio
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_crm.models import (
    AuditEvent,
    ErasureRecord,
    LegalHold,
    OperationalEvent,
    OutboxEvent,
)
from tests.api.agent_helpers import API, headers

Factory = async_sessionmaker[AsyncSession]
ADMIN = "user-d"


async def make(client: AsyncClient, resource: str, body: dict[str, Any], tenant: str = "tenant-a"):
    response = await client.post(f"{API}/{resource}", headers=headers(ADMIN, tenant), json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def erase(client: AsyncClient, resource: str, record_id: str, user: str = ADMIN,
                tenant: str = "tenant-a", reason: str = "data subject request"):
    return await client.post(
        f"{API}/admin/erasure/{resource}/{record_id}",
        headers=headers(user, tenant),
        json={"reason": reason},
    )


async def hold(client: AsyncClient, body: dict[str, Any], tenant: str = "tenant-a"):
    return await client.post(f"{API}/admin/legal-holds", headers=headers(ADMIN, tenant), json=body)


async def purge(client: AsyncClient, dry_run: bool):
    return await client.post(
        f"{API}/admin/retention/purge", headers=headers(ADMIN), json={"dry_run": dry_run}
    )


async def count(factory: Factory, model: Any) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_contact_erasure_overwrites_personal_fields_and_keeps_the_row(
    client: AsyncClient,
) -> None:
    contact = await make(
        client, "contacts",
        {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com",
         "company_name": "Analytical Engines"},
    )
    task = await make(client, "tasks", {"title": "Call Ada", "contact_id": contact["id"]})

    response = await erase(client, "contacts", contact["id"])

    assert response.status_code == 200, response.text
    assert response.json()["record_id"] == contact["id"]
    after = (await client.get(f"{API}/contacts/{contact['id']}", headers=headers(ADMIN))).json()
    assert (after["first_name"], after["last_name"]) == ("[erased]", "[erased]")
    assert after["email"] is None and after["company_name"] is None
    assert after["archived_at"] is not None and after["version"] == contact["version"] + 1
    linked = (await client.get(f"{API}/tasks/{task['id']}", headers=headers(ADMIN))).json()
    assert linked["contact_id"] == contact["id"]


@pytest.mark.parametrize(
    ("resource", "body", "erased"),
    [
        ("companies", {"name": "Secret Corp"}, {"name": "[erased]"}),
        ("opportunities", {"name": "Deal for Ada", "next_step": "call Ada"},
         {"name": "[erased]", "next_step": None}),
        ("tasks", {"title": "Call Ada", "description": "her mobile"},
         {"title": "[erased]", "description": None}),
        ("activities", {"kind": "note", "subject": "Met Ada", "body": "private"},
         {"subject": "[erased]", "body": None}),
    ],
)
async def test_other_resources_are_anonymised_in_place(
    client: AsyncClient, resource: str, body: dict[str, Any], erased: dict[str, Any]
) -> None:
    anchor = await make(client, "contacts", {"first_name": "Anchor", "last_name": "Contact"})
    if resource in {"opportunities", "activities"}:
        body = {**body, "contact_id": anchor["id"]}
    record = await make(client, resource, body)

    assert (await erase(client, resource, record["id"])).status_code == 200

    exported = await client.get(f"{API}/admin/export/{resource}", headers=headers(ADMIN))
    row = next(item for item in exported.json() if item["id"] == record["id"])
    for key, value in erased.items():
        assert row[key] == value


async def test_erasure_is_idempotent_and_audited_without_personal_values(
    client: AsyncClient, session_factory: Factory
) -> None:
    contact = await make(
        client, "contacts", {"first_name": "Grace", "last_name": "Hopper", "email": "g@x.io"}
    )

    first = await erase(client, "contacts", contact["id"])
    second = await erase(client, "contacts", contact["id"], reason="another reason")

    assert first.json()["id"] == second.json()["id"]
    assert second.json()["reason"] == "data subject request"
    assert await count(session_factory, ErasureRecord) == 1
    async with session_factory() as session:
        events = list(await session.scalars(select(OperationalEvent)))
        audits = list(await session.scalars(select(AuditEvent)))
        outbox = list(await session.scalars(select(OutboxEvent)))
    erased_audits = [item for item in audits if item.action == "record.erased"]
    assert len(erased_audits) == 1
    assert any(item.event_type == "record.erased" for item in outbox)
    blob = str(
        [e.payload for e in events] + [a.details for a in audits] + [o.payload for o in outbox]
    )
    assert "Grace" not in blob and "Hopper" not in blob and "g@x.io" not in blob


async def test_concurrent_erasures_leave_one_record(
    client: AsyncClient, session_factory: Factory
) -> None:
    contact = await make(client, "contacts", {"first_name": "A", "last_name": "B"})

    results = await asyncio.gather(*(erase(client, "contacts", contact["id"]) for _ in range(4)))

    assert {r.status_code for r in results} == {200}
    assert await count(session_factory, ErasureRecord) == 1


async def test_validation_unknown_resource_and_missing_reason(client: AsyncClient) -> None:
    contact = await make(client, "contacts", {"first_name": "A", "last_name": "B"})

    assert (await erase(client, "widgets", contact["id"])).status_code == 404
    assert (await erase(client, "contacts", "no-such-id")).status_code == 404
    blank = await client.post(
        f"{API}/admin/erasure/contacts/{contact['id']}", headers=headers(ADMIN), json={"reason": ""}
    )
    assert blank.status_code == 422


@pytest.mark.parametrize("user", ["user-a", "user-b", "user-c"])
async def test_only_admins_can_erase_or_hold(
    client: AsyncClient, session_factory: Factory, user: str
) -> None:
    contact = await make(client, "contacts", {"first_name": "A", "last_name": "B"})

    denied = await erase(client, "contacts", contact["id"], user=user)
    denied_hold = await client.post(
        f"{API}/admin/legal-holds", headers=headers(user),
        json={"scope": "tenant", "reason": "case"},
    )
    listing = await client.get(f"{API}/admin/legal-holds", headers=headers(user))

    assert denied.status_code == denied_hold.status_code == listing.status_code == 403
    assert await count(session_factory, ErasureRecord) == 0
    assert await count(session_factory, LegalHold) == 0
    async with session_factory() as session:
        denials = await session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "authorization.denied"
            )
        )
    assert (denials or 0) >= 3


async def test_other_tenants_records_and_holds_are_invisible(client: AsyncClient) -> None:
    mine = await make(client, "contacts", {"first_name": "A", "last_name": "B"})
    theirs = await make(client, "contacts", {"first_name": "C", "last_name": "D"}, "tenant-b")
    their_hold = (await hold(client, {"scope": "tenant", "reason": "theirs"}, "tenant-b")).json()

    assert (await erase(client, "contacts", theirs["id"])).status_code == 404
    cross = await hold(client, {"scope": "record", "resource_type": "contacts",
                                "record_id": theirs["id"], "reason": "x"})
    assert cross.status_code == 404
    listing = await client.get(f"{API}/admin/legal-holds", headers=headers(ADMIN))
    assert listing.json() == []
    release = await client.post(
        f"{API}/admin/legal-holds/{their_hold['id']}/release",
        headers=headers(ADMIN), json={"reason": "x"},
    )
    assert release.status_code == 404
    assert (await erase(client, "contacts", mine["id"])).status_code == 200


async def test_hold_validation(client: AsyncClient) -> None:
    contact = await make(client, "contacts", {"first_name": "A", "last_name": "B"})

    both = await hold(client, {"scope": "tenant", "resource_type": "contacts", "reason": "r"})
    missing = await hold(client, {"scope": "record", "reason": "r"})
    unknown = await hold(client, {"scope": "record", "resource_type": "widgets",
                                  "record_id": contact["id"], "reason": "r"})
    empty = await hold(client, {"scope": "tenant", "reason": ""})

    assert both.status_code == missing.status_code == unknown.status_code == 422
    assert empty.status_code == 422


async def test_record_hold_blocks_erasure_until_released(
    client: AsyncClient, session_factory: Factory
) -> None:
    held = await make(client, "contacts", {"first_name": "A", "last_name": "B"})
    free = await make(client, "contacts", {"first_name": "C", "last_name": "D"})
    created = await hold(client, {"scope": "record", "resource_type": "contacts",
                                  "record_id": held["id"], "reason": "litigation"})
    assert created.status_code == 201, created.text

    blocked = await erase(client, "contacts", held["id"])
    other = await erase(client, "contacts", free["id"])

    assert blocked.status_code == 409 and blocked.json()["code"] == "legal_hold"
    assert other.status_code == 200
    unchanged = (await client.get(f"{API}/contacts/{held['id']}", headers=headers(ADMIN))).json()
    assert unchanged["first_name"] == "A"
    async with session_factory() as session:
        denied = await session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "record.erase", AuditEvent.outcome == "denied"
            )
        )
    assert denied == 1

    released = await client.post(
        f"{API}/admin/legal-holds/{created.json()['id']}/release",
        headers=headers(ADMIN), json={"reason": "case closed"},
    )
    assert released.status_code == 200 and released.json()["released_at"] is not None
    again = await client.post(
        f"{API}/admin/legal-holds/{created.json()['id']}/release",
        headers=headers(ADMIN), json={"reason": "again"},
    )
    assert again.status_code == 409
    assert (await erase(client, "contacts", held["id"])).status_code == 200


async def test_tenant_hold_blocks_erasure_and_real_purges_but_not_dry_runs(
    client: AsyncClient,
) -> None:
    contact = await make(client, "contacts", {"first_name": "A", "last_name": "B"})
    created = (await hold(client, {"scope": "tenant", "reason": "investigation"})).json()

    assert (await erase(client, "contacts", contact["id"])).status_code == 409
    dry = await purge(client, True)
    real = await purge(client, False)
    assert dry.status_code == 200 and dry.json()["legal_hold_active"] is True
    assert real.status_code == 409 and real.json()["code"] == "legal_hold"
    active = await client.get(f"{API}/admin/legal-holds?active=true", headers=headers(ADMIN))
    assert [item["id"] for item in active.json()] == [created["id"]]

    await client.post(
        f"{API}/admin/legal-holds/{created['id']}/release",
        headers=headers(ADMIN), json={"reason": "done"},
    )
    assert (await purge(client, False)).status_code == 200
    assert (await purge(client, True)).json()["legal_hold_active"] is False
    assert (await erase(client, "contacts", contact["id"])).status_code == 200
    inactive = await client.get(f"{API}/admin/legal-holds?active=false", headers=headers(ADMIN))
    assert [item["id"] for item in inactive.json()] == [created["id"]]


async def test_erased_records_cannot_be_edited_or_unarchived(client: AsyncClient) -> None:
    contact = await make(client, "contacts", {"first_name": "Ada", "last_name": "L"})
    task = await make(client, "tasks", {"title": "Call"})
    await erase(client, "contacts", contact["id"])
    await erase(client, "tasks", task["id"])
    version = (await client.get(f"{API}/contacts/{contact['id']}", headers=headers(ADMIN))).json()

    revive = await client.patch(
        f"{API}/contacts/{contact['id']}",
        headers={**headers(ADMIN), "If-Match": f'"{version["version"]}"'},
        json={"archived": False, "first_name": "Ada"},
    )
    retitle = await client.patch(
        f"{API}/tasks/{task['id']}",
        headers={**headers(ADMIN), "If-Match": '"2"'},
        json={"title": "Call Ada again"},
    )

    assert revive.status_code == 409 and retitle.status_code == 409
    after = (await client.get(f"{API}/contacts/{contact['id']}", headers=headers(ADMIN))).json()
    assert after["first_name"] == "[erased]" and after["archived_at"] is not None


async def test_repeating_a_hold_does_not_stack_and_blank_reasons_are_rejected(
    client: AsyncClient,
) -> None:
    first = await hold(client, {"scope": "tenant", "reason": "case 1"})
    second = await hold(client, {"scope": "tenant", "reason": "retry of case 1"})
    blank = await hold(client, {"scope": "tenant", "reason": "   "})
    long_id = await erase(client, "contacts", "x" * 80)

    assert first.json()["id"] == second.json()["id"]
    listing = await client.get(f"{API}/admin/legal-holds?active=true", headers=headers(ADMIN))
    assert len(listing.json()) == 1
    assert blank.status_code == 422 and long_id.status_code == 422
