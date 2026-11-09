import sys
from datetime import timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_crm.config import settings
from ai_crm.main import app
from ai_crm.models import RequestMetricBucket, utc_now
from ai_crm.observability.requests import RequestRecorder, flush_request_metrics
from tests.api.agent_helpers import API, headers

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> RequestRecorder:
    rec = RequestRecorder(max_keys=100)
    monkeypatch.setattr("ai_crm.middleware.request_recorder", rec)
    monkeypatch.setattr(settings, "request_metrics_enabled", True)
    return rec


def add(rec: RequestRecorder, count: int, ms: float, cls: str = "2xx", tenant: str = "tenant-a",
        when=None) -> None:
    for _ in range(count):
        rec.record(now=when or utc_now(), tenant_id=tenant, route="/r", method="GET",
                   status_class=cls, latency_ms=ms)


async def api_slos(client: AsyncClient, tenant: str = "tenant-a") -> dict[str, Any]:
    response = await client.get(f"{API}/observability/slos", headers=headers("user-d", tenant))
    assert response.status_code == 200, response.text
    return {item["key"]: item for item in response.json()["slos"]}


async def stored(factory: Factory) -> list[RequestMetricBucket]:
    async with factory() as session:
        return list(await session.scalars(select(RequestMetricBucket)))


def test_recorder_buckets_latency_and_caps_distinct_keys() -> None:
    rec = RequestRecorder(max_keys=2)
    now = utc_now()
    for ms in (10, 25, 26, 6000):
        rec.record(now=now, tenant_id="t", route="/a", method="GET", status_class="2xx",
                   latency_ms=ms)
    bucket = next(iter(rec.drain().values()))
    assert bucket.count == 4 and bucket.latency_counts == [2, 1, 0, 0, 0, 0, 0, 0, 1]

    for route in ("/a", "/b", "/c", "/d", "/e"):
        rec.record(now=now, tenant_id="t", route=route, method="GET", status_class="2xx",
                   latency_ms=1)
    keys = {key[2] for key in rec.drain()}
    assert keys == {"/a", "/b", "other"}


def test_recorder_restore_merges_and_drops_beyond_the_hard_cap() -> None:
    rec = RequestRecorder(max_keys=1)
    now = utc_now()
    add(rec, 2, 5)
    drained = rec.drain()
    add(rec, 1, 5)
    rec.restore(drained)
    assert next(iter(rec.drain().values())).count == 3
    for status_class in ("2xx", "3xx", "4xx", "5xx"):
        rec.record(now=now, tenant_id="t", route="/a", method="GET", status_class=status_class,
                   latency_ms=1)
    assert rec.dropped >= 1 and len(rec.drain()) <= 2


async def test_requests_are_recorded_by_route_template_and_tenant(
    client: AsyncClient, recorder: RequestRecorder
) -> None:
    created = await client.post(
        f"{API}/contacts",
        headers=headers("user-a", "tenant-a"),
        json={"first_name": "Ada", "last_name": "Lovelace"},
    )
    assert created.status_code == 201, created.text
    await client.get(f"{API}/contacts/{created.json()['id']}", headers=headers("user-a"))
    await client.get(f"{API}/contacts/missing-id", headers=headers("user-a"))
    await client.get(f"{API}/contacts", headers={"X-Tenant-ID": "tenant-a"})

    seen = {(k[1], k[2], k[4]) for k in recorder.drain()}
    assert ("tenant-a", "/contacts/{contact_id}", "2xx") in seen
    assert ("tenant-a", "/contacts/{contact_id}", "4xx") in seen
    assert ("", "/contacts", "4xx") in seen
    assert not any(created.json()["id"] in route for _, route, _ in seen)


async def test_forged_tenant_header_without_membership_lands_in_the_platform_bucket(
    client: AsyncClient, recorder: RequestRecorder
) -> None:
    response = await client.get(f"{API}/contacts", headers=headers("user-b", "tenant-b"))
    assert response.status_code == 403

    assert {key[1] for key in recorder.drain()} == {""}


async def test_five_xx_counts_as_error_and_unhandled_exceptions_are_recorded(
    client: AsyncClient, recorder: RequestRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def not_ready() -> None:
        raise SQLAlchemyError("down")

    async def crash() -> None:
        raise RuntimeError("boom")

    # The routes package re-exports a function named health, so reach the module via sys.modules.
    health_module = sys.modules["ai_crm.api.routes.health"]
    monkeypatch.setattr(health_module, "check_database", not_ready)
    assert (await client.get(f"{API}/readiness")).status_code == 503
    monkeypatch.setattr(health_module, "check_database", crash)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as raw:
        assert (await raw.get(f"{API}/readiness")).status_code == 500

    totals = {k[4]: v.count for k, v in recorder.drain().items()}
    assert totals == {"5xx": 2}


async def test_kill_switch_503_is_not_counted_as_an_error(
    client: AsyncClient, recorder: RequestRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "disabled_capabilities", "ai")
    response = await client.post(
        f"{API}/ai/customer-summary",
        headers={**headers("user-a"), "Idempotency-Key": "k-1"},
        json={"query": "renewal"},
    )
    assert response.status_code == 503

    assert {k[4] for k in recorder.drain()} == {"disabled"}


async def test_disabled_recording_stores_nothing(client: AsyncClient) -> None:
    from ai_crm.observability.requests import request_recorder

    before = request_recorder.drain()
    await client.get(f"{API}/health")
    assert request_recorder.drain() == {}
    request_recorder.restore(before)


async def test_slos_without_traffic_stay_no_data(client: AsyncClient) -> None:
    result = await api_slos(client)
    for key in ("api_availability", "api_latency_p95_ms", "api_error_rate"):
        assert result[key]["status"] == "no_data" and result[key]["value"] is None


async def test_slo_values_come_from_the_flushed_buckets(
    client: AsyncClient, session_factory: Factory
) -> None:
    rec = RequestRecorder(100)
    add(rec, 98, 10)
    add(rec, 2, 3000, "5xx")
    add(rec, 5, 10, "4xx")
    add(rec, 3, 10, "disabled")
    assert await flush_request_metrics(session_factory, rec) > 0

    result = await api_slos(client)

    assert result["api_error_rate"]["value"] == pytest.approx(2 / 105)
    assert result["api_availability"]["value"] == pytest.approx(1 - 2 / 105)
    assert result["api_error_rate"]["status"] == "breached"
    assert result["api_availability"]["status"] == "breached"
    assert result["api_latency_p95_ms"]["value"] == 25
    assert result["api_latency_p95_ms"]["status"] == "met"
    assert result["api_error_rate"]["detail"]["requests"] == 105


async def test_p95_is_the_upper_bound_of_its_bucket_and_can_breach(
    client: AsyncClient, session_factory: Factory
) -> None:
    rec = RequestRecorder(100)
    add(rec, 90, 10)
    add(rec, 10, 700)
    await flush_request_metrics(session_factory, rec)

    result = await api_slos(client)

    assert result["api_latency_p95_ms"]["value"] == 1000
    assert result["api_latency_p95_ms"]["status"] == "breached"


async def test_rows_from_several_processes_are_summed_and_tenants_are_isolated(
    client: AsyncClient, session_factory: Factory
) -> None:
    first, second, other = RequestRecorder(100), RequestRecorder(100), RequestRecorder(100)
    add(first, 50, 10)
    add(second, 50, 10, "5xx")
    add(other, 100, 10, "5xx", tenant="tenant-b")
    for rec in (first, second, other):
        await flush_request_metrics(session_factory, rec)

    mine = await api_slos(client, "tenant-a")
    theirs = await api_slos(client, "tenant-b")

    assert mine["api_error_rate"]["value"] == pytest.approx(0.5)
    assert theirs["api_error_rate"]["value"] == pytest.approx(1.0)
    assert (await api_slos(client, "tenant-a"))["api_error_rate"]["detail"]["requests"] == 100


async def test_a_failed_flush_keeps_the_counts_for_the_next_attempt(
    session_factory: Factory,
) -> None:
    rec = RequestRecorder(100)
    add(rec, 3, 10)

    def broken():
        raise RuntimeError("database down")

    assert await flush_request_metrics(broken, rec) == 0  # type: ignore[arg-type]
    assert await flush_request_metrics(session_factory, rec) == 1
    assert sum(row.count for row in await stored(session_factory)) == 3


async def test_retention_purges_old_request_buckets_for_the_tenant_only(
    client: AsyncClient, session_factory: Factory
) -> None:
    old = utc_now() - timedelta(days=settings.observability_retention_days + 5)
    rec = RequestRecorder(100)
    add(rec, 1, 10, when=old)
    add(rec, 1, 10, when=old, tenant="tenant-b")
    add(rec, 1, 10)
    await flush_request_metrics(session_factory, rec)

    dry = await client.post(
        f"{API}/admin/retention/purge", headers=headers("user-d"), json={"dry_run": True}
    )
    assert dry.json()["counts"]["request_metric_buckets"] == 1
    assert len(await stored(session_factory)) == 3

    done = await client.post(
        f"{API}/admin/retention/purge", headers=headers("user-d"), json={"dry_run": False}
    )
    assert done.json()["counts"]["request_metric_buckets"] == 1
    async with session_factory() as session:
        remaining = (
            await session.execute(
                select(RequestMetricBucket.tenant_id, func.count()).group_by(
                    RequestMetricBucket.tenant_id
                )
            )
        ).all()
    assert sorted((tenant, count) for tenant, count in remaining) == [
        ("tenant-a", 1),
        ("tenant-b", 1),
    ]


async def test_unusual_methods_and_long_routes_are_normalised_so_flushes_cannot_poison(
    client: AsyncClient, recorder: RequestRecorder
) -> None:
    await client.request("FOOBARBAZQUXYZ", f"{API}/contacts", headers=headers("user-a"))
    await client.get("/" + "x" * 400)

    keys = recorder.drain()
    assert {key[3] for key in keys} <= {"OTHER", "GET"}
    assert all(len(key[2]) <= 200 and len(key[3]) <= 10 for key in keys)


async def test_platform_5xx_before_tenant_verification_is_visible_in_slo_detail(
    client: AsyncClient, session_factory: Factory
) -> None:
    rec = RequestRecorder(100)
    add(rec, 4, 10, "5xx", tenant="")
    add(rec, 10, 10)
    await flush_request_metrics(session_factory, rec)

    result = await api_slos(client)

    assert result["api_error_rate"]["detail"]["platform_5xx_requests"] == 4
    assert result["api_error_rate"]["value"] == 0


async def test_lifespan_flushes_request_metrics_on_shutdown(
    session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_crm.main as main_module
    from ai_crm.observability.requests import request_recorder

    async def noop() -> None:
        return None

    monkeypatch.setattr(main_module, "SessionFactory", session_factory)
    monkeypatch.setattr(main_module, "close_database", noop)
    monkeypatch.setattr(settings, "request_metrics_enabled", True)
    monkeypatch.setattr(settings, "auto_create_tables", False)
    monkeypatch.setattr(settings, "request_metrics_flush_seconds", 60)
    request_recorder.drain()
    request_recorder.record(now=utc_now(), tenant_id="tenant-a", route="/r", method="GET",
                            status_class="2xx", latency_ms=5)

    async with main_module.lifespan(app):
        pass

    assert [row.count for row in await stored(session_factory)] == [1]
