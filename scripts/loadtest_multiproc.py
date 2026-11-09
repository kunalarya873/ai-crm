"""Multi-process load and correctness harness on PostgreSQL.

Starts N real API processes and M worker processes (uvicorn, one event loop each) against a
fresh schema in a PostgreSQL database, drives them over HTTP with the operation mix from
loadtest.py, then queues real knowledge-index jobs and checks that the workers ran every job
exactly once. It also reconciles the request metrics the servers flushed (Phase 10J) against the
requests the client sent.

Local evidence only: client, servers and database share one machine, providers are fixtures.

    uv run python scripts/loadtest_multiproc.py \
        --database-url postgresql+psycopg_async://postgres@127.0.0.1:54329/crm_test \
        --matrix 1/1,2/2,4/2 --json /tmp/multiproc.json
"""

import argparse
import asyncio
import json
import os
import random
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
# A real (non-default) secret lets the servers run with DEBUG off: DEBUG enables SQL echo, which
# would slow every statement and distort the numbers.
os.environ.setdefault("AUTH_SECRET_KEY", "multiproc-load-test-secret-0123456789abcdef")

import httpx  # noqa: E402
from loadtest import API, Stats, create_tenants, headers, seed, workload  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from ai_crm.models import Base  # noqa: E402

TENANT_WEIGHTS = (70, 10, 10, 5, 5)


class Fleet:
    """Round-robins requests across the API processes and counts every one it sends."""

    def __init__(self, urls: list[str]) -> None:
        self.clients = [httpx.AsyncClient(base_url=url, timeout=120) for url in urls]
        self.sent = 0
        self._next = 0

    def _pick(self) -> httpx.AsyncClient:
        client = self.clients[self._next % len(self.clients)]
        self._next += 1
        self.sent += 1
        return client

    def get(self, *args: Any, **kwargs: Any) -> Any:
        return self._pick().get(*args, **kwargs)

    def post(self, *args: Any, **kwargs: Any) -> Any:
        return self._pick().post(*args, **kwargs)

    def patch(self, *args: Any, **kwargs: Any) -> Any:
        return self._pick().patch(*args, **kwargs)

    async def close(self) -> None:
        for client in self.clients:
            await client.aclose()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def scoped_url(base: str, schema: str) -> str:
    url = make_url(base).update_query_dict({"options": f"-csearch_path={schema}"})
    return url.render_as_string(hide_password=False)


def start_server(
    url: str, log_dir: Path, name: str, *, worker: bool
) -> tuple[subprocess.Popen, str]:
    port = free_port()
    env = {
        **os.environ,
        "DATABASE_URL": url,
        "DEBUG": "false",
        "AUTO_CREATE_TABLES": "false",
        "SEED_DEMO_DATA": "false",
        "WORKER_ENABLED": "true" if worker else "false",
        "WORKER_POLL_SECONDS": "0.2",
        "MAX_QUEUED_JOBS_PER_TENANT": "100000",
        "REQUEST_METRICS_ENABLED": "true",
        "REQUEST_METRICS_FLUSH_SECONDS": "2",
    }
    log = open(log_dir / f"{name}.log", "w")  # noqa: SIM115 - lives as long as the process
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "ai_crm.main:app", "--app-dir", str(ROOT / "src"),
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT,
    )
    return process, f"http://127.0.0.1:{port}"


async def wait_ready(urls: list[str]) -> int:
    polls = 0
    async with httpx.AsyncClient(timeout=5) as client:
        for url in urls:
            for _ in range(200):
                try:
                    reply = await client.get(f"{url}{API}/health")
                    polls += 1  # only answered requests are recorded by the server
                    if reply.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.25)
            else:
                raise RuntimeError(f"server at {url} did not become ready")
    return polls


async def queue_index_jobs(
    fleet: Fleet, factory: Any, tenants: list[str], jobs: int, run_at: str
) -> int:
    async with factory() as session:
        rows = (await session.execute(text("select tenant_id, id from knowledge_sources"))).all()
    sources: dict[str, list[str]] = {}
    for tenant, source_id in rows:
        sources.setdefault(tenant, []).append(source_id)
    gate = asyncio.Semaphore(16)
    queued = 0

    async def one(index: int) -> None:
        nonlocal queued
        tenant = tenants[index % len(tenants)]
        if not sources.get(tenant):
            return
        source_id = sources[tenant][index % len(sources[tenant])]
        async with gate:
            made = await fleet.post(f"{API}/knowledge/sources/{source_id}/index",
                                    headers=headers(tenant))
            if made.status_code not in (200, 201, 202):
                return
            job = await fleet.post(
                f"{API}/jobs",
                headers=headers(tenant, {"Idempotency-Key": f"mp-{index}"}),
                json={
                    "job_type": "knowledge.index",
                    "payload": {"index_job_id": made.json()["id"]},
                    "run_at": run_at,
                },
            )
            queued += 1 if job.status_code == 201 else 0

    await asyncio.gather(*(one(i) for i in range(jobs)))
    return queued


async def wait_drained(factory: Any, timeout: float) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        async with factory() as session:
            open_jobs = await session.scalar(text(
                "select count(*) from durable_jobs where job_type = 'knowledge.index' "
                "and status in ('queued', 'running', 'retryable')"))
        if not open_jobs:
            break
        await asyncio.sleep(0.2)
    return time.perf_counter() - started


async def correctness(factory: Any) -> dict[str, Any]:
    async def rows(sql: str) -> list[tuple[Any, ...]]:
        async with factory() as session:
            return [tuple(row) for row in (await session.execute(text(sql))).all()]

    statuses = dict(await rows(
        "select status, count(*) from durable_jobs where job_type = 'knowledge.index' "
        "group by status"))
    attempts = dict(await rows(
        "select attempts, count(*) from durable_jobs where job_type = 'knowledge.index' "
        "group by attempts"))
    index_status = dict(
        await rows("select status, count(*) from knowledge_index_jobs group by status")
    )
    spans = await rows(
        "select tenant_id, extract(epoch from max(completed_at)) "
        "- extract(epoch from min(created_at)) "
        "from durable_jobs where job_type = 'knowledge.index' and completed_at is not null "
        "group by tenant_id")
    return {
        "durable_job_status": statuses,
        "durable_job_attempts": {str(k): v for k, v in attempts.items()},
        "index_job_status": index_status,
        "per_tenant_seconds_to_finish": {t: round(float(s), 2) for t, s in spans},
        "every_job_ran_exactly_once": set(statuses) <= {"succeeded"} and set(attempts) <= {1},
    }


async def busy_window(factory: Any) -> dict[str, Any]:
    """Worker throughput over the span from the first job start to the last completion, so it
    does not depend on how fast the client could queue jobs."""
    async with factory() as session:
        count, seconds = (
            await session.execute(
                text(
                    "select count(*), extract(epoch from max(completed_at) - min(started_at)) "
                    "from durable_jobs where job_type = 'knowledge.index' "
                    "and completed_at is not null"
                )
            )
        ).one()
    seconds = float(seconds or 0)
    return {
        "worker_busy_seconds": round(seconds, 2),
        "jobs_per_s": round(count / seconds, 1) if seconds else 0.0,
    }


async def run_config(args: argparse.Namespace, api: int, workers: int) -> dict[str, Any]:
    schema = f"mp_{uuid4().hex[:12]}"
    base = args.database_url
    admin = create_async_engine(base, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(base, connect_args={"options": f"-csearch_path={schema}"})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    processes: list[subprocess.Popen] = []
    fleet: Fleet | None = None
    result: dict[str, Any] = {"api_processes": api, "worker_processes": workers}
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        tenants = [f"mp-tenant-{i}" for i in range(len(TENANT_WEIGHTS))]
        await create_tenants(factory, tenants)
        log_dir = Path(tempfile.mkdtemp(prefix="mp-logs-"))
        url = scoped_url(base, schema)
        api_urls, worker_urls = [], []
        for number in range(api):
            process, address = start_server(url, log_dir, f"api{number}", worker=False)
            processes.append(process)
            api_urls.append(address)
        for number in range(workers):
            process, address = start_server(url, log_dir, f"worker{number}", worker=True)
            processes.append(process)
            worker_urls.append(address)
        polls = await wait_ready(api_urls + worker_urls)
        fleet = Fleet(api_urls)
        client = cast(httpx.AsyncClient, fleet)  # same get/post/patch surface the harness uses
        contacts = {}
        for tenant in tenants:
            big = tenant == tenants[0]
            contacts[tenant], _ = await seed(client, tenant, args.contacts if big else 20,
                                             args.sources if big else 5)
        stats = Stats()
        wall = await workload(client, stats, random.Random(args.seed), tenants, TENANT_WEIGHTS,
                              contacts, args.ops, args.concurrency)
        result["workload"] = {"wall_seconds": round(wall, 2), "operations": stats.report(wall)}
        started = time.perf_counter()
        # All jobs share one future run_at, so they become ready together and the
        # workers' drain rate is not capped by how fast the client can queue them.
        run_at = (datetime.now(UTC) + timedelta(seconds=args.gate_seconds)).isoformat()
        queued = await queue_index_jobs(fleet, factory, tenants, args.jobs, run_at)
        queue_seconds = time.perf_counter() - started
        drain_seconds = await wait_drained(factory, args.drain_timeout)
        result["drain"] = {
            "jobs_queued": queued,
            "queueing_seconds": round(queue_seconds, 2),
            "seconds_until_idle": round(drain_seconds, 2),
        }
        result["drain"].update(await busy_window(factory))
        result["correctness"] = await correctness(factory)
        sent = fleet.sent + polls
    finally:
        if fleet is not None:
            await fleet.close()
        for process in processes:
            process.send_signal(signal.SIGTERM)  # graceful: the servers flush request metrics
        for process in processes:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
    async with factory() as session:
        recorded = await session.scalar(
            text("select coalesce(sum(count), 0) from request_metric_buckets")
        )
    result["request_metrics"] = {"client_sent": sent, "recorded": int(recorded or 0)}
    async with admin.connect() as connection:
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()
    await admin.dispose()
    return result


def render(results: list[dict[str, Any]]) -> str:
    lines = ["api/workers  wall_s  list p50/p95  create p50/p95  search p50/p95  drain j/s  "
             "once  metrics(sent/recorded)"]
    for item in results:
        ops = item["workload"]["operations"]

        def pair(name: str) -> str:
            return f"{ops[name]['p50_ms']}/{ops[name]['p95_ms']}" if name in ops else "-"

        metrics = item["request_metrics"]
        lines.append(
            f"{item['api_processes']}/{item['worker_processes']:<9} "
            f"{item['workload']['wall_seconds']:<7} {pair('contacts.list'):<13} "
            f"{pair('contacts.create'):<15} {pair('knowledge.search'):<15} "
            f"{item['drain']['jobs_per_s']:<10} "
            f"{'yes' if item['correctness']['every_job_ran_exactly_once'] else 'NO':<5} "
            f"{metrics['client_sent']}/{metrics['recorded']}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="postgresql+psycopg_async://...")
    parser.add_argument("--matrix", default="1/1,2/2", help="API/worker process counts")
    parser.add_argument("--ops", type=int, default=1500)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--contacts", type=int, default=500)
    parser.add_argument("--sources", type=int, default=50)
    parser.add_argument("--jobs", type=int, default=600)
    parser.add_argument("--gate-seconds", type=float, default=8,
                        help="jobs become ready this long after the run starts queueing")
    parser.add_argument("--drain-timeout", type=float, default=180)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()
    results = []
    for entry in args.matrix.split(","):
        api, workers = (int(part) for part in entry.split("/"))
        print(f"== {api} API / {workers} worker processes", flush=True)
        results.append(asyncio.run(run_config(args, api, workers)))
    print(render(results))
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
