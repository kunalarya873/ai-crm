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
6. A queue that stays old with no failures usually means the worker is not running
   (`WORKER_ENABLED=false`, or the process is down). Restart it; jobs are leased, so nothing is lost.

Job types with no handler (for example `reminder.dispatch`) stay `queued` on purpose until an
external worker exists.
