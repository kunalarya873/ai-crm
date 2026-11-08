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

Read the current SLOs with `GET /observability/slos` (owner is `SLO_OWNER`). The three API SLOs
(availability, latency, error rate) report `not_measured`: there is no per-request telemetry yet,
so use your load balancer or APM for those.

Every procedure ends the same way: write down what you saw, what you changed, and the audit or
trace ids (`GET /observability/events?trace_id=<32-hex>` follows one request across the API and
the worker).
