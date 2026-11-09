# Runbooks

Operator procedures for the AI CRM backend. Every endpoint below is relative to `/api/v1`, needs
`Authorization: Bearer <jwt>` and `X-Tenant-ID`, and is checked against the app's OpenAPI schema
by `tests/api/test_runbooks.py`, so a renamed endpoint breaks the build instead of the runbook.

Start with the signal:

| Signal | Runbook |
|---|---|
| `queue_age_seconds` or `job_success_rate` SLO breached; dead-lettered jobs | [failed-jobs.md](failed-jobs.md) |
| `sync_freshness_seconds` breached; connection `needs_reauth` alert | [failed-syncs.md](failed-syncs.md) |
| `action_completion_rate` breached; execution `failed`, `recoverable` or `uncertain` | [failed-actions.md](failed-actions.md) |
| `ai_fallback_rate` or `ai_avg_latency_ms` breached; a bad AI answer was reported | [ai-output-issues.md](ai-output-issues.md) |
| A user cannot see or change something, or sees something they should not | [data-access-issues.md](data-access-issues.md) |
| `agent_overdue_runs` breached; an agent run is stuck or escalated | [stuck-agent-runs.md](stuck-agent-runs.md) |
| An incident needs a capability stopped now | [kill-switches.md](kill-switches.md) |
| An audit question, a customer export request, or telemetry growth | [data-lifecycle.md](data-lifecycle.md) |

Schema changes and rollbacks follow [../migrations.md](../migrations.md).

Read the current SLOs with `GET /observability/slos` (owner is `SLO_OWNER`). The three API SLOs
(availability, p95 latency, 5xx error rate) come from per-minute request counts the app records in
memory and flushes to `request_metric_buckets` every `REQUEST_METRICS_FLUSH_SECONDS`; with no
traffic in the window they report `no_data`. They measure time inside the app only (not the load
balancer or network), p95 is the upper bound of its histogram bucket, and kill-switch 503s are not
counted as errors.

Every procedure ends the same way: write down what you saw, what you changed, and the audit or
trace ids (`GET /observability/events?trace_id=<32-hex>` follows one request across the API and
the worker).
