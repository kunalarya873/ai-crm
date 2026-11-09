# Failed or stuck jobs

**Signals:** `queue_age_seconds` or `job_success_rate` breached; jobs in `dead_letter` or `failed`.

1. List the problem jobs: `GET /jobs?status=dead_letter` (also `failed`, `retryable`, `queued`).
2. Open one: `GET /jobs/{job_id}`. Read `error_code`, `error_detail`, `attempts` and `trace_id`.
3. Find what happened around it: `GET /observability/events?trace_id=<trace_id>`.
4. Decide:
   - Transient cause (provider outage, timeout) that has passed: `POST /jobs/{job_id}/retry`.
   - Permanent cause (bad payload, revoked connection): fix the cause first, then retry, or
     `POST /jobs/{job_id}/cancel` if the work is no longer wanted.
   - Jobs stuck `running` after a worker crash: `POST /jobs/reconcile-expired` releases expired
     leases (the worker also does this every tick).
5. If `integration.*` jobs are simply waiting, check whether the `connectors` kill switch is on:
   `GET /admin/feature-flags`. Jobs stay `queued` while it is off and run when it is turned back on.
6. The worker only visits tenants that have claimable ready jobs, expired leases or overdue agent
   runs, so a job enqueued just now can wait up to one poll interval (`WORKER_POLL_SECONDS`).
   Job types with no handler never make a tenant busy.
7. `POST /jobs` returning `429 backpressure` means the tenant already has
   `MAX_QUEUED_JOBS_PER_TENANT` queued or retryable jobs. Wait for `Retry-After` and let the worker
   drain the backlog; do not raise the limit to hide a stuck queue. A repeat of the same
   `Idempotency-Key` still returns the original job.
8. Connector jobs waiting with no kill switch and no failures usually mean the provider circuit
   breaker is open: after `CONNECTOR_BREAKER_FAILURES` transient sync failures in a row, connector
   jobs stay queued for `CONNECTOR_BREAKER_COOLDOWN_SECONDS`, then one job probes. The state is in
   the worker process only; restarting the worker resets it.
9. A queue that stays old with no failures usually means the worker is not running
   (`WORKER_ENABLED=false`, or the process is down). Restart it; jobs are leased, so nothing is lost.

Job types with no handler (for example `reminder.dispatch`) stay `queued` on purpose until an
external worker exists.
