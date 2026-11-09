# Capacity evidence (local, SQLite)

**Read this first.** Everything here comes from `scripts/loadtest.py`, which drives the real app
in-process (httpx ASGI transport) against a throwaway SQLite file on one laptop: one process, one
event loop, no network, no Postgres. It shows relative bottlenecks of app plus SQLite. It is **not**
a supported-scale claim, and the numbers will not transfer to Postgres or a multi-process
deployment.

## Run it

```bash
uv run python scripts/loadtest.py --profile smoke                       # about 1 s
uv run python scripts/loadtest.py --profile standard --explain --json out.json   # about 30 s
uv run python scripts/loadtest.py --profile wide                        # adds a 500-tenant tick
```

Flags: `--ops`, `--concurrency`, `--seed`. The smoke profile also runs as a test
(`tests/test_loadtest_smoke.py`) to keep the harness working; it asserts no timing thresholds.
Load runs are deliberately not part of CI.

## What it does

Five tenants weighted 70/10/10/5/5 (the large tenant has about 2,150 contacts and 200 indexed
knowledge sources), then a mixed workload at concurrency 8 over 1,500 operations: about 55%
contact list pages (keyset, no point reads), 15% contact create, 10% contact update with
`If-Match`, 10% knowledge search, 10% job enqueue. The seed fixes the operation plan (which
operation, on which tenant), so the mix is repeatable; how the eight workers interleave is not, so
latencies vary between runs. Afterwards it drains the job queue with the worker and measures the
worker tick as tenants are added, checking that the ticks handled no jobs.

## Results

Run on 2026-11-09 at commit `acdf63a` plus the review fixes to the harness; macOS arm64, 8 CPUs,
Python 3.12.12; seed 7, database about 10 MB (`wide` profile). Latencies in milliseconds. No
request errors and no rejected enqueues.

| Operation | Requests | req/s | p50 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|---:|
| contacts.list | 803 | 122.1 | 10.7 | 24.2 | 41.2 | 100.4 |
| contacts.create | 241 | 36.6 | 28.8 | 261.4 | 973.3 | 1175.6 |
| contacts.update | 156 | 23.7 | 25.5 | 207.8 | 578.9 | 777.7 |
| knowledge.search | 161 | 24.5 | 15.3 | 48.3 | 97.0 | 99.3 |
| jobs.enqueue | 139 | 21.1 | 35.9 | 276.0 | 1386.2 | 1395.6 |

Worker: 439 jobs (300 drain jobs plus the backlog the workload enqueued) in 3.7 s, about 120
jobs/s with a no-op handler.

Worker tick with no ready jobs (`wide` profile): before the fix 15 tenants 0.04 s, 105 tenants
0.22 s, 505 tenants 1.07 s (about 2.1 ms per tenant). After the fix (10G, below) the same tick takes
about 1 ms at 15, 105 and 505 tenants. Tail latencies are noisy: across four runs the write p99
ranged from 310 ms to 1,386 ms, while the medians stayed within a few milliseconds.

## Findings

1. **Writes are the bottleneck, and their tail is long.** Reads are about 10 ms at the median.
   Writes are 25 to 36 ms at the median but 200 to 280 ms at p95 and up to 1.4 s at the worst,
   while eight workers contend for SQLite's single writer. Each write also stores an audit event,
   an outbox event and an operational event in the same transaction, so every write holds the lock
   for several inserts. Whether this is acceptable depends on the real database; it needs
   re-measuring on Postgres.
2. **The worker tick cost about 2 ms per tenant even with no ready jobs. Idle ticks fixed in 10G; interval ticks unchanged.** It
   listed every tenant and ran reconciliation, a claim attempt and overdue-run checks for each, so
   a tick would have passed the 5 s poll interval at roughly 2,400 tenants on this machine. The
   worker now runs one index-backed discovery query per tick (ready or expired jobs, overdue agent
   runs; migration 0016 adds the two indexes) and visits only those tenants: an idle tick is about
   1 ms and flat from 15 to 505 tenants. Ticks that run proactive checks or schedule syncs (every
   300 s by default) still visit every tenant and still cost per tenant; that cost was not
   measured separately. Busy tenants still cost per-tenant work.
3. **No plain table scans on tenant-owned tables** in the query shapes captured during the
   workload (`--explain`, SQLite `EXPLAIN QUERY PLAN`). The only scans are of the `organizations`
   index, which is how the worker lists tenants. This covers the statements the workload issued at
   this data size, not every query in the app, and says nothing about other databases' planners.
4. **Knowledge search** was 15 ms at the median over 200 sources in the large tenant. Search is
   lexical in Python over indexed chunks; behaviour with tens of thousands of sources is unmeasured.

## Capacity assumptions

| Dimension | Status |
|---|---|
| Contacts per large tenant | Measured: about 2,150 with reads at 10 ms p50. Beyond that, assumed. |
| Knowledge sources per tenant | Measured: 200. Beyond that, assumed. |
| Concurrent API clients | Measured: 8 in one process. More processes: unmeasured. |
| Job throughput | Measured: about 120 jobs/s no-op, single worker. Real handlers (sync, indexing): unmeasured. |
| Tenants per worker | Measured: idle tick about 1 ms flat up to 505 tenants (after 10G). Interval ticks (proactive checks, sync scheduling) are still O(tenants) and unmeasured. |
| Queued jobs per tenant | Configured cap `MAX_QUEUED_JOBS_PER_TENANT=1000`; behaviour near the cap under load unmeasured. |
| Integrations, webhooks, AI usage, agent runs | Not load tested. |
| Postgres, connection pools, long transactions | Not tested; there is no Postgres lane. |

## Still open

Load against a running server or Postgres, multi-process workers, soak and failure-injection
tests, and performance fixes for the findings above.
