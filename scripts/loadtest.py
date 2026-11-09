"""Local load and capacity harness.

Drives the real app in-process (httpx ASGITransport) against a throwaway SQLite file, so it
measures app plus SQLite on one machine. It is evidence about relative bottlenecks, not a
supported-scale claim: no Postgres, no network, one process, one event loop.

    uv run python scripts/loadtest.py --profile standard --json /tmp/load.json
"""

import argparse
import asyncio
import json
import os
import platform
import random
import re
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

os.environ.setdefault("DEBUG", "true")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402
from sqlalchemy import event, text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ai_crm.auth import create_access_token  # noqa: E402
from ai_crm.db import build_engine, get_session  # noqa: E402
from ai_crm.main import app  # noqa: E402
from ai_crm.models import Base, Membership, Organization, User  # noqa: E402
from ai_crm.permissions import Permission  # noqa: E402
from ai_crm.work import handlers as handlers_module  # noqa: E402
from ai_crm.work.runner import run_tick  # noqa: E402

API = "/api/v1"
OPERATIONS = (
    "contacts.list",
    "contacts.create",
    "contacts.update",
    "knowledge.search",
    "jobs.enqueue",
)
WEIGHTS = (55, 15, 10, 10, 10)
ADMIN = "load-admin"


@dataclass(frozen=True)
class Profile:
    tenant_weights: tuple[int, ...]
    contacts_large: int
    sources_large: int
    ops: int
    concurrency: int
    drain_jobs: int
    idle_tenants: tuple[int, ...]


PROFILES = {
    "smoke": Profile((60, 40), 20, 4, 40, 4, 12, (3,)),
    "standard": Profile((70, 10, 10, 5, 5), 2000, 200, 1500, 8, 300, (10, 100)),
    "wide": Profile((70, 10, 10, 5, 5), 2000, 200, 1500, 8, 300, (10, 100, 500)),
}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


class Stats:
    def __init__(self) -> None:
        self.latencies: dict[str, list[float]] = defaultdict(list)
        self.errors: dict[str, Counter[str]] = defaultdict(Counter)

    def record(self, operation: str, seconds: float, status: int | str) -> None:
        self.latencies[operation].append(seconds * 1000)
        if isinstance(status, str) or status >= 400:
            self.errors[operation][str(status)] += 1

    def report(self, wall_seconds: float) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for operation in OPERATIONS:
            values = self.latencies.get(operation, [])
            if not values:
                continue
            result[operation] = {
                "count": len(values),
                "errors": dict(self.errors.get(operation, {})),
                "throughput_per_s": round(len(values) / wall_seconds, 1),
                "p50_ms": round(percentile(values, 0.50), 2),
                "p95_ms": round(percentile(values, 0.95), 2),
                "p99_ms": round(percentile(values, 0.99), 2),
                "max_ms": round(max(values), 2),
            }
        return result


def headers(tenant: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(ADMIN)}",
        "X-Tenant-ID": tenant,
        **(extra or {}),
    }


async def create_tenants(
    factory: async_sessionmaker[AsyncSession], names: list[str]
) -> None:
    async with factory() as session:
        session.add(User(id=ADMIN, email="load@example.com", display_name="Load Admin"))
        for name in names:
            session.add(Organization(id=name, name=name))
            session.add(Membership(tenant_id=name, user_id=ADMIN, role="admin"))
        await session.commit()


async def seed(
    client: httpx.AsyncClient, tenant: str, contacts: int, sources: int
) -> tuple[list[tuple[str, int]], int]:
    contact_ids: list[tuple[str, int]] = []
    for index in range(contacts):
        response = await client.post(
            f"{API}/contacts",
            headers=headers(tenant),
            json={"first_name": f"First{index}", "last_name": f"Last{index % 50}"},
        )
        response.raise_for_status()
        contact_ids.append((response.json()["id"], int(response.json()["version"])))
    indexed = 0
    for index in range(sources):
        body = " ".join(f"topic{(index + n) % 40} renewal pricing contract" for n in range(30))
        created = await client.post(
            f"{API}/knowledge/sources",
            headers=headers(tenant),
            json={
                "source_type": "document",
                "source_record_id": f"note-{index}",
                "title": f"Account note {index}",
                "content": body,
            },
        )
        created.raise_for_status()
        queued = await client.post(
            f"{API}/knowledge/sources/{created.json()['id']}/index", headers=headers(tenant)
        )
        queued.raise_for_status()
        ran = await client.post(
            f"{API}/knowledge/index-jobs/{queued.json()['id']}/run", headers=headers(tenant)
        )
        ran.raise_for_status()
        indexed += 1
    return contact_ids, indexed


async def timed(
    stats: Stats, operation: str, call: Any
) -> httpx.Response | None:
    started = time.perf_counter()
    try:
        response = await call
    except Exception as error:  # noqa: BLE001 - failures are data, not crashes
        stats.record(operation, time.perf_counter() - started, type(error).__name__)
        return None
    stats.record(operation, time.perf_counter() - started, response.status_code)
    return response


async def workload(
    client: httpx.AsyncClient,
    stats: Stats,
    rng: random.Random,
    tenants: list[str],
    weights: tuple[int, ...],
    contacts: dict[str, list[tuple[str, int]]],
    ops: int,
    concurrency: int,
) -> float:
    # The operation mix is fixed up front from the seed, and every operation type appears at
    # least once; only the interleaving between workers varies from run to run.
    plan: list[tuple[int, str, str, int]] = []
    for index in range(ops):
        operation = (
            OPERATIONS[index] if index < len(OPERATIONS) else rng.choices(OPERATIONS, WEIGHTS)[0]
        )
        plan.append((index, rng.choices(tenants, weights)[0], operation, rng.randrange(1 << 30)))
    counter = iter(plan)
    cursors: dict[str, str | None] = {}

    async def worker(worker_id: int) -> None:
        for index, tenant, operation, op_seed in counter:
            local = random.Random(op_seed)
            known = contacts.get(tenant, [])
            if operation == "contacts.update" and not known:
                operation = "contacts.list"
            if operation == "contacts.list":
                params: dict[str, Any] = {"limit": 50}
                if cursors.get(tenant) and local.random() < 0.5:
                    params["cursor"] = cursors[tenant]
                response = await timed(
                    stats,
                    operation,
                    client.get(f"{API}/contacts", headers=headers(tenant), params=params),
                )
                if response is not None and response.status_code == 200:
                    cursors[tenant] = response.headers.get("X-Next-Cursor")
            elif operation == "contacts.create":
                response = await timed(
                    stats,
                    operation,
                    client.post(
                        f"{API}/contacts",
                        headers=headers(tenant),
                        json={"first_name": f"New{index}", "last_name": "Load"},
                    ),
                )
                if response is not None and response.status_code == 201:
                    known.append((response.json()["id"], int(response.json()["version"])))
            elif operation == "contacts.update" and known:
                # Reserve the contact while it is being updated so concurrent workers do not
                # race on one If-Match version; that conflict is correct behaviour, not load.
                contact_id, version = known.pop(local.randrange(len(known)))
                response = await timed(
                    stats,
                    operation,
                    client.patch(
                        f"{API}/contacts/{contact_id}",
                        headers=headers(tenant, {"If-Match": f'"{version}"'}),
                        json={"company_name": f"Acme {local.randrange(1000)}"},
                    ),
                )
                if response is not None and response.status_code == 200:
                    known.append((contact_id, int(response.json()["version"])))
                else:
                    known.append((contact_id, version))
            elif operation == "knowledge.search":
                await timed(
                    stats,
                    operation,
                    client.get(
                        f"{API}/knowledge/search",
                        headers=headers(tenant),
                        params={"q": f"topic{local.randrange(40)} pricing", "limit": 10},
                    ),
                )
            elif operation == "jobs.enqueue":
                await timed(
                    stats,
                    operation,
                    client.post(
                        f"{API}/jobs",
                        headers=headers(tenant, {"Idempotency-Key": f"load-{index}-{tenant}"}),
                        json={"job_type": "notification.send", "payload": {}},
                    ),
                )

    started = time.perf_counter()
    await asyncio.gather(*(worker(number) for number in range(concurrency)))
    return time.perf_counter() - started


async def drain(
    client: httpx.AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    tenants: list[str],
    jobs: int,
) -> dict[str, Any]:
    async def ok(session: AsyncSession, context: Any, job: Any) -> dict[str, bool]:
        return {"ok": True}

    original = dict(handlers_module.HANDLERS)
    handlers_module.HANDLERS["notification.send"] = (ok, frozenset({Permission.WORK_MANAGE}))
    try:
        enqueued = 0
        rejected = 0
        for index in range(jobs):
            tenant = tenants[index % len(tenants)]
            response = await client.post(
                f"{API}/jobs",
                headers=headers(tenant, {"Idempotency-Key": f"drain-{index}"}),
                json={"job_type": "notification.send", "payload": {}},
            )
            if response.status_code == 201:
                enqueued += 1
            else:
                rejected += 1
        handled = 0
        ticks = 0
        started = time.perf_counter()
        while True:
            done = await run_tick(factory)
            ticks += 1
            handled += done
            if done == 0 or ticks > 10_000:
                break
        elapsed = time.perf_counter() - started
    finally:
        handlers_module.HANDLERS.clear()
        handlers_module.HANDLERS.update(original)
    return {
        "jobs_enqueued": enqueued,
        "enqueue_rejected": rejected,
        "jobs_handled": handled,
        "ticks": ticks,
        "seconds": round(elapsed, 3),
        "jobs_per_s": round(handled / elapsed, 1) if elapsed else 0.0,
    }


async def tick_cost(
    factory: async_sessionmaker[AsyncSession], idle_counts: tuple[int, ...]
) -> list[dict[str, Any]]:
    results = []
    existing = 0
    for target in idle_counts:
        async with factory() as session:
            for number in range(existing, target):
                session.add(Organization(id=f"idle-{number}", name=f"idle {number}"))
                session.add(Membership(tenant_id=f"idle-{number}", user_id=ADMIN, role="member"))
            await session.commit()
        existing = target
        async with factory() as session:
            counted = await session.execute(text("SELECT COUNT(*) FROM organizations"))
            total = int(counted.scalar() or 0)
        samples = []
        handled_during_ticks = 0
        for _ in range(3):
            started = time.perf_counter()
            handled_during_ticks += await run_tick(factory)
            samples.append(time.perf_counter() - started)
        results.append(
            {
                "tenants": total,
                "jobs_handled_during_ticks": handled_during_ticks,
                "tick_seconds_median": round(statistics.median(samples), 3),
                "ms_per_tenant": round(statistics.median(samples) * 1000 / total, 2),
            }
        )
    return results


def explain_plans(statements: dict[str, tuple[str, Any]], connection: Any) -> list[dict[str, Any]]:
    findings = []
    for shape, (sql, params) in list(statements.items()):
        if not sql.lstrip().upper().startswith("SELECT"):
            continue
        try:
            rows = connection.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, params).fetchall()
        except Exception:  # noqa: BLE001 - some captured shapes cannot be re-planned
            continue
        details = [str(row[-1]) for row in rows]
        scans = [detail for detail in details if detail.startswith("SCAN ")]
        if scans:
            findings.append(
                {
                    "statement": shape[:160],
                    "scans": scans,
                    # A plain scan reads the whole table; a scan "USING ... INDEX" reads a whole
                    # index (cheaper, but still unbounded).
                    "full_table": any(
                        re.fullmatch(r"SCAN (TABLE )?\S+( AS \S+)?", scan) for scan in scans
                    ),
                }
            )
    return findings


async def run(
    profile_name: str,
    ops: int | None,
    concurrency: int | None,
    seed_value: int,
    explain: bool,
    sqlite_mode: str = "default",
    database_url: str | None = None,
) -> dict[str, Any]:
    profile = PROFILES[profile_name]
    rng = random.Random(seed_value)
    tenants = [f"load-{number}" for number in range(len(profile.tenant_weights))]
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "load.db"
        schema: str | None = None
        if database_url:
            # A throwaway schema keeps the run away from anything else in the database.
            schema = f"load_{uuid4().hex[:12]}"
            admin = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
            async with admin.connect() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await admin.dispose()
            engine = create_async_engine(
                database_url, connect_args={"options": f"-csearch_path={schema}"}
            )
            explain = False  # EXPLAIN QUERY PLAN output is SQLite-specific
        else:
            engine = build_engine(f"sqlite+aiosqlite:///{database}", wal=sqlite_mode == "wal")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await create_tenants(factory, tenants)

        async def override_session():  # noqa: ANN202
            async with factory() as session:
                yield session

        previous_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_session] = override_session
        captured: dict[str, tuple[str, Any]] = {}
        capturing = [explain]

        def capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ANN202
            if capturing[0]:
                captured.setdefault(" ".join(statement.split()), (statement, parameters))

        if explain:
            event.listen(engine.sync_engine, "before_cursor_execute", capture)

        transport = httpx.ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://load") as client:
                total_weight = sum(profile.tenant_weights)
                contacts: dict[str, list[tuple[str, int]]] = {}
                sources: dict[str, int] = {}
                seed_started = time.perf_counter()
                for tenant, weight in zip(tenants, profile.tenant_weights, strict=True):
                    share = weight / total_weight
                    contacts[tenant], sources[tenant] = await seed(
                        client,
                        tenant,
                        max(5, int(profile.contacts_large * share / 0.7)),
                        max(2, int(profile.sources_large * share / 0.7)),
                    )
                seed_seconds = time.perf_counter() - seed_started
                captured.clear()

                stats = Stats()
                wall = await workload(
                    client,
                    stats,
                    rng,
                    tenants,
                    profile.tenant_weights,
                    contacts,
                    ops or profile.ops,
                    concurrency or profile.concurrency,
                )
                workload_report = stats.report(wall)
                drain_report = await drain(client, factory, tenants, profile.drain_jobs)
                tick_report = await tick_cost(factory, profile.idle_tenants)
                plans: list[dict[str, Any]] = []
                capturing[0] = False
                if explain:
                    async with engine.connect() as connection:
                        plans = await connection.run_sync(
                            lambda sync_conn: explain_plans(captured, sync_conn)
                        )
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous_overrides)
            await engine.dispose()
        size_mb = round(database.stat().st_size / 1_048_576, 2) if database.exists() else 0.0
        if database_url and schema:
            admin = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
            async with admin.connect() as connection:
                total = await connection.scalar(
                    text(
                        "SELECT COALESCE(SUM(pg_total_relation_size(c.oid)), 0) FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = :schema AND c.relkind = 'r'"
                    ),
                    {"schema": schema},
                )
                size_mb = round(float(total or 0) / 1_048_576, 2)
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()
    return {
        "profile": profile_name,
        "database": "postgres" if database_url else "sqlite",
        "sqlite_mode": None if database_url else sqlite_mode,
        "seed": seed_value,
        "ops": ops or profile.ops,
        "concurrency": concurrency or profile.concurrency,
        "tenants": dict(zip(tenants, profile.tenant_weights, strict=True)),
        "seeded": {
            "contacts": {tenant: len(rows) for tenant, rows in contacts.items()},
            "knowledge_sources": sources,
            "seconds": round(seed_seconds, 2),
        },
        "wall_seconds": round(wall, 2),
        "operations": workload_report,
        "worker_drain": drain_report,
        "tick_cost": tick_report,
        "table_scans": plans if explain else None,
        "database_mb": size_mb,
        "machine": {
            "cpus": os.cpu_count(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
    }


def render(report: dict[str, Any]) -> str:
    lines = [
        f"profile={report['profile']} db={report['database']}/{report['sqlite_mode']} "
        f"ops={report['ops']} "
        f"concurrency={report['concurrency']} "
        f"wall={report['wall_seconds']}s db={report['database_mb']}MB",
        f"{'operation':<18}{'count':>7}{'err':>5}{'req/s':>9}"
        f"{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}",
    ]
    for name, row in report["operations"].items():
        lines.append(
            f"{name:<18}{row['count']:>7}{sum(row['errors'].values()):>5}"
            f"{row['throughput_per_s']:>9}{row['p50_ms']:>9}{row['p95_ms']:>9}"
            f"{row['p99_ms']:>9}{row['max_ms']:>9}"
        )
    drain_row = report["worker_drain"]
    lines.append(
        f"worker drain: {drain_row['jobs_handled']} jobs in {drain_row['seconds']}s "
        f"({drain_row['jobs_per_s']} jobs/s, {drain_row['ticks']} ticks)"
    )
    for row in report["tick_cost"]:
        lines.append(
            f"idle tick with {row['tenants']} tenants: {row['tick_seconds_median']}s "
            f"({row['ms_per_tenant']} ms/tenant, {row['jobs_handled_during_ticks']} jobs handled)"
        )
    if report["table_scans"]:
        lines.append("scans in captured queries (full_table = no index used):")
        lines.extend(
            f"  full_table={item['full_table']} {item['scans']} <- {item['statement']}"
            for item in report["table_scans"]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="standard")
    parser.add_argument("--ops", type=int)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--sqlite-mode", choices=["default", "wal"], default="default")
    parser.add_argument(
        "--database-url",
        help="PostgreSQL URL (postgresql+psycopg_async://...); runs in a throwaway schema",
    )
    arguments = parser.parse_args()
    report = asyncio.run(
        run(
            arguments.profile,
            arguments.ops,
            arguments.concurrency,
            arguments.seed,
            arguments.explain,
            arguments.sqlite_mode,
            arguments.database_url,
        )
    )
    print(render(report))
    if arguments.json_path:
        Path(arguments.json_path).write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
