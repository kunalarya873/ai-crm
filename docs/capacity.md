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
   while eight workers contend for SQLite's single writer (see the WAL experiment below: it
   helps writes but hurt reads and throughput here). Each write also stores an audit event,
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

## SQLite write-path experiment (10H)

Hypothesis: SQLite's default rollback journal serialises writers and fsyncs every commit, so WAL
mode (`journal_mode=WAL`, `synchronous=NORMAL`) should shorten the write tail. Tested with
`scripts/loadtest.py --profile standard --sqlite-mode default|wal`, three runs per mode, same
seed, same machine. The table shows the median of the three runs (p50 / p95 / p99 in ms); the
per-run spread was large, for example default `contacts.update` p99 of 758, 1,064 and 875.

| Operation | default | WAL |
|---|---|---|
| contacts.create | 25 / 162 / 555 | 27 / 100 / 356 |
| contacts.update | 25 / 264 / 875 | 30 / 101 / 130 |
| jobs.enqueue | 29 / 262 / 771 | 35 / 142 / 465 |
| contacts.list | 10 / 21 / 43 | 33 / 49 / 61 |
| knowledge.search | 14 / 42 / 64 | 94 / 259 / 276 |
| wall time for 1,500 ops | 6.0 s | 8.7 s |

Result: **mixed, so WAL stays off by default.** It cut the write p95 by roughly 40 to 60 percent
and the write p99 by roughly 35 to 85 percent, but it made reads two to six times slower at the
median and the whole run 45 percent longer. The read regression was not diagnosed (a growing WAL
file between checkpoints, or reads now running concurrently with writes and competing for CPU,
are guesses, not findings). The setting is `SQLITE_WAL=true` (default false) and applies to
SQLite only. WAL is not safe on network filesystems and leaves `*.db-wal` and `*.db-shm`
files beside the database. The busy timeout is Python's 5 s default in both modes; turning WAL off again switches a file that was left in WAL back to the default journal. Postgres write behaviour is
still unmeasured.

## PostgreSQL run (10I)

The same `standard` profile against a throwaway local PostgreSQL 15.3 (Postgres.app, default
settings, TCP on localhost, one throwaway schema per run), via
`--database-url postgresql+psycopg_async://...`. Three runs; medians of p50 / p95 / p99 in ms.
No request errors. Same laptop, same seed. Not a production claim: one node, no replication, no
pooler, no tuning, client and server on one machine.

| Operation | SQLite (default journal) | PostgreSQL |
|---|---|---|
| contacts.list | 10 / 21 / 43 | 18 / 38 / 78 |
| contacts.create | 25 / 162 / 555 | 37 / 85 / 120 |
| contacts.update | 25 / 264 / 875 | 39 / 88 / 158 |
| knowledge.search | 14 / 42 / 64 | 58 / 119 / 226 |
| jobs.enqueue | 29 / 262 / 771 | 43 / 97 / 128 |
| wall time, 1,500 ops | 6.0 s | 6.5 s |
| worker drain | about 130 jobs/s | about 118 jobs/s |
| idle worker tick | about 1 ms | about 1 ms |

What it shows: the write tail is much shorter on PostgreSQL (p95 85 to 97 ms against 160 to 260 ms,
p99 120 to 160 ms against 555 to 875 ms), which supports the earlier reading that the long tail
was SQLite's single writer and fsync-per-commit, not the number of rows written per request. The
medians are higher than SQLite's, because every statement is now a network round trip instead of
an in-process call. Knowledge search is the clearest case: it issues several queries per request
and is about four times slower at the median. That makes the number of statements per request, not
only per write, the next thing to look at on PostgreSQL. Run-to-run spread was still large.

## Request telemetry overhead (10J)

The middleware now counts every request in memory (`REQUEST_METRICS_ENABLED`). `standard`
profile, SQLite default mode, two runs with it on and two off, laptop, in-process harness (the
background flush task is not running in the harness, so this measures the middleware only):

| Operation | p50 on (ms) | p50 off (ms) |
|---|---|---|
| contacts.list | 10.9 / 10.1 | 10.5 / 12.8 |
| contacts.create | 28.5 / 26.6 | 27.7 / 38.5 |
| jobs.enqueue | 29.4 / 32.3 | 33.7 / 38.4 |

Medians sit inside the run-to-run spread (the off runs were not faster), so no cost can be
distinguished from noise at this scale; tails varied by 2 to 3 times between identical runs, as
before. The flush writes one row per (minute, tenant, route, method, status class) every 30
seconds, which is a handful of rows per tick under this load; its cost on a busy multi-process
deployment is not measured.

## Multiple processes on PostgreSQL (10L)

`scripts/loadtest_multiproc.py` starts N real API processes and M worker processes (uvicorn, one
event loop each, `DEBUG` off) against a fresh schema in a local PostgreSQL 15, drives the API over
HTTP with the same operation mix as `loadtest.py` (1,500 operations, 16 concurrent clients,
500 contacts and 50 knowledge sources on the large tenant), then queues 600 real `knowledge.index`
jobs that all become ready at the same instant (`run_at` a few seconds ahead), so the drain rate
is not capped by how fast the client can queue them. Apple M2, 8 cores, 8 GB, client, servers and
database on the same machine. Two full runs; each cell is run 1 / run 2.

```bash
uv run python scripts/loadtest_multiproc.py \
  --database-url postgresql+psycopg_async://postgres@127.0.0.1:54329/crm_mp \
  --matrix 1/1,2/1,2/2,4/2,4/4 --json /tmp/multiproc.json
```

| API / worker processes | list p50 (ms) | create p50 (ms) | search p50 (ms) | worker jobs/s |
|---|---|---|---|---|
| 1 / 1 | 24.8 / 24.9 | 48.1 / 49.1 | 39.9 / 37.9 | 88 / 78 |
| 2 / 1 | 17.4 / 17.1 | 23.2 / 23.6 | 20.0 / 20.5 | 87 / 79 |
| 2 / 2 | 21.2 / 17.7 | 32.0 / 24.0 | 28.9 / 20.1 | 67 / 185 |
| 4 / 2 | 18.2 / 17.3 | 24.3 / 23.4 | 19.6 / 17.6 | 133 / 186 |
| 4 / 4 | 21.7 / 19.7 | 28.6 / 26.4 | 22.8 / 21.2 | 111 / 268 |

Correctness held in all ten configurations (6,000 jobs): every `knowledge.index` job finished
`succeeded` with `attempts = 1`, none were left running, no request failed, the servers logged no
errors or tracebacks, and each tenant's jobs finished within about 0.7 seconds of the others'
(no tenant starved). The request metrics from 10J reconciled exactly: the number of requests the
client sent equalled the sum of `request_metric_buckets.count` across all processes in every
configuration (for example 3,498 sent, 3,498 recorded), after a graceful shutdown flushed them.

What it shows: a second API process roughly halves the median latency of writes and searches
against one process (the single event loop was the limit); further API processes help less.
Worker throughput rose from about 80 to 90 jobs/s for one worker to somewhere between 110 and 270
for four, but the two runs of the same configuration differed by up to 2.8 times (2/2 gave 67 and
185), so the scaling factor is not established. Do not read a speed-up figure from this table.
An earlier version of the harness ran the servers with `DEBUG` on, which turns on SQL echo; its
numbers were slower and are not used.

## Capacity assumptions

| Dimension | Status |
|---|---|
| Contacts per large tenant | Measured: about 2,150 with reads at 10 ms p50. Beyond that, assumed. |
| Knowledge sources per tenant | Measured: 200. Beyond that, assumed. |
| Concurrent API clients | Measured: 8 in one process (SQLite), 16 over HTTP across 1 to 4 processes (PostgreSQL, 10L). More: unmeasured. |
| Job throughput | Measured: about 120 jobs/s no-op, single worker. Real handlers (sync, indexing): unmeasured. |
| Tenants per worker | Measured: idle tick about 1 ms flat up to 505 tenants (after 10G). Interval ticks (proactive checks, sync scheduling) are still O(tenants) and unmeasured. |
| Queued jobs per tenant | Configured cap `MAX_QUEUED_JOBS_PER_TENANT=1000`; behaviour near the cap under load unmeasured. |
| Integrations, webhooks, AI usage, agent runs | Not load tested. |
| Postgres | Test suite, migrations and one load profile run against a local PostgreSQL 15 (10I). Production sizing, pooling, replication, long transactions and online-migration lock behaviour: not tested. |

## Still open

Soak and failure-injection tests (killing a worker mid-job, database restarts), a network between
client, servers and database, and performance fixes for the findings above.
