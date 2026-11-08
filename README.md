# AI CRM Backend

This is the runnable backend for the AI-first CRM and business automation platform described in `Target.md`.

## Current implementation: Backend Phases 1, 2, 3A, 4, 5A, 6A, 7A, 8A, 9A, 9B, 10A (kill switches), 10B (SLOs, usage, runbooks), 10C (audit lookup, export, telemetry retention), and 10D (worker fairness, circuit breaker, backpressure)

The backend currently implements the runtime/security foundation, core CRM vertical slice, provider-neutral integration foundation, permission-aware knowledge retrieval, durable work execution, grounded AI requests, approval-gated action execution, and operational measurement:

- FastAPI application with versioned routes under `/api/v1`.
- SQLite with async SQLAlchemy for local development and a configurable database URL.
- Alembic migrations for the Phase 1 through Phase 10A schemas.
- Tenant-scoped organisations, users, memberships, companies, contacts, opportunities, activities, and tasks.
- Signed JWT bearer authentication for local development.
- Role-based permissions for CRM reads, creates, and updates.
- Correlation IDs returned in responses and stored with audit events.
- Audit events for successful writes and denied permission checks.
- Transactional outbox events for CRM creates and updates.
- Optimistic concurrency for mutable CRM records using `version` and `If-Match`.
- Customer timelines combining activities and tasks.
- Activity source-record deduplication and legacy company-name backfill.
- Provider-neutral integration connections and fixture connector.
- Sync runs, cursors, leases, record links, and imported canonical activities.
- Signed webhook verification, replay protection, and queued webhook envelopes.
- Idempotent external-write records with disconnected-connection protection.
- Knowledge source registry with visibility, ownership, sensitivity, freshness, and AI-use policy.
- Retry-safe versioned indexing jobs with chunk replacement and failure visibility.
- Permission-aware lexical search with stable pagination, structured filters, freshness, and provenance.
- Bounded context assemblies with AI eligibility, sensitivity filtering, citations, and insufficient-evidence results.
- Durable work items for tasks, commitments, handoffs, approvals, reminders, and escalations.
- Dependency-aware work transitions with ownership, due dates, timezone validation, completion evidence, and transition history.
- Durable typed jobs with idempotency keys, priority queues, delayed execution, worker leases, heartbeats, timeouts, retries, dead-letter state, and manual recovery.
- Deduplicated reminder deliveries linked to durable jobs with delivery and acknowledgement state.
- Allowlisted workflow instances with versioned steps, approval pauses, resume support, outputs, and transition history.
- Provider-neutral AI gateway with deterministic `fixture` adapter, timeout handling, provider health, usage estimates, and cost accounting.
- Reviewable JSON prompt catalog with persisted prompt/model/config versions for every AI run.
- Typed customer summary, field extraction, next-step recommendation, communication draft, and workflow-plan use cases.
- AI runs with bounded authorised context, evidence references, structured-output validation, safe fallbacks, idempotency, audit events, and human feedback.
- Typed action registry with approval policy, required permissions, risk levels, affected resources, and expected side effects.
- Version-aware action proposals with edit, approve, reject, revoke, expiration, dry-run, and source-AI evidence support.
- Controlled internal task, contact, activity, and approval-work-item execution plus fixture-backed external activity writes.
- Idempotent action effects with execution state, record-version rechecks, provider error mapping, retry, uncertain-outcome reconciliation, and operator notes.
- Redacted operational events with event versions, correlation IDs, deduplication, and tenant-scoped drill-down.
- Stored metric observations and summaries for AI usage/cost/latency/intervention, action and job failures, overdue work, and event volume.
- Transparent proactive checks for overdue work, inactive opportunities, failed jobs, and failed or uncertain actions.
- Deduplicated system/business alerts linked to reviewable escalation work items with acknowledgement and resolution notes.
- Validation, tenant isolation, and cross-tenant relationship protection.
- Async API tests with an isolated temporary database.

The local JWT secret is only a development boundary. A production deployment must replace it with an external identity provider or a managed signing-key configuration before external users or sensitive data are supported.

## Setup

Requirements:

- Python 3.12 or newer.
- `uv`.

Install dependencies:

```bash
uv sync --extra dev
```

Run the API:

```bash
uv run uvicorn ai_crm.main:app --app-dir src --reload
```

Outside `DEBUG=true`, startup fails unless `AUTH_SECRET_KEY` is set to a non-default value of at least 32 characters (see `.env.example`).

Set `WORKER_ENABLED=true` to run the in-process worker, which executes `integration.sync`, `integration.webhook` and `knowledge.index` jobs, runs proactive checks every `PROACTIVE_CHECK_INTERVAL_SECONDS`, and enqueues one incremental sync per healthy connection every `INTEGRATION_SYNC_INTERVAL_SECONDS`. Accepted webhooks enqueue an `integration.webhook` job that triggers an incremental sync (the payload is only a hint, never trusted as record data); transient provider failures retry with backoff that grows across consecutive failed syncs, while permanent ones fail once and pause scheduled syncs for that connection until a manual sync succeeds. Revoked connections are terminal. It is off by default and meant for a single process; job types it has no handler for, including `reminder.dispatch` until a real delivery channel exists, are left queued for external workers. A webhook for a revoked or disconnected connection is rejected with 409.

List endpoints for contacts, companies, opportunities and tasks accept `limit` plus either `offset` or an opaque `cursor`. When a full page is returned, the `X-Next-Cursor` response header carries the cursor for the next page (use it instead of `offset`; combining both is a 422). Results are ordered newest-first with `id` as tiebreak, so cursor pages stay stable while records are created.

The API will be available at `http://127.0.0.1:8000`. OpenAPI documentation is available at `/docs`.

Run the database migrations explicitly for a production-like startup:

```bash
uv run alembic upgrade head
```

For local development, the default configuration can create the schema automatically. Set `AUTO_CREATE_TABLES=false` when migrations are managed outside the process.

## Example requests

Generate a local development token for the seeded `demo-user` when running with `DEBUG=true` and `SEED_DEMO_DATA=true`:

```bash
TOKEN=$(uv run python -c 'from ai_crm.auth import create_access_token; print(create_access_token("demo-user"))')
```

Create a contact:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/contacts \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -H 'X-Tenant-ID: demo-tenant' \
  -d '{"first_name":"Ada","last_name":"Lovelace","email":"ada@example.com"}'
```

List contacts for a tenant:

```bash
curl http://127.0.0.1:8000/api/v1/contacts \
  -H "Authorization: Bearer $TOKEN" \
  -H 'X-Tenant-ID: demo-tenant'
```

Create a task:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -H 'X-Tenant-ID: demo-tenant' \
  -d '{"title":"Schedule follow-up"}'
```

Update a contact using optimistic concurrency:

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/contacts/<contact-id> \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -H 'X-Tenant-ID: demo-tenant' \
  -H 'If-Match: "1"' \
  -d '{"status":"qualified"}'
```

Phase 2 endpoints include:

```text
POST/GET/PATCH /companies
GET            /companies/{company_id}
POST/GET/PATCH /opportunities
GET            /opportunities/{opportunity_id}
POST           /activities
GET            /contacts/{contact_id}/timeline
GET            /opportunities/{opportunity_id}/timeline
GET/PATCH      /contacts/{contact_id}
GET/PATCH      /tasks/{task_id}
```

Phase 3A integration endpoints include:

```text
POST/GET /integrations/connections
POST     /integrations/connections/{connection_id}/test
POST     /integrations/connections/{connection_id}/refresh
POST     /integrations/connections/{connection_id}/disconnect
POST     /integrations/connections/{connection_id}/revoke
POST     /integrations/connections/{connection_id}/sync
GET      /integrations/connections/{connection_id}/sync-runs
GET      /integrations/connections/{connection_id}/links
POST     /integrations/connections/{connection_id}/writes
POST     /integrations/webhooks/{provider_key}
```

The only enabled provider is `fixture`. It is deterministic and exists for connector contract tests and local development; it is not a production integration. Create one locally with:

```bash
CONNECTION=$(curl -sS -X POST http://127.0.0.1:8000/api/v1/integrations/connections \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -H 'X-Tenant-ID: demo-tenant' \
  -d '{"provider_key":"fixture","external_account_id":"demo-account","scopes":["activities:read"],"secret_ref":"demo-webhook-secret"}')
```

The `secret_ref` is an opaque secret reference in the application contract. The fixture adapter uses it directly only to make local webhook signature tests deterministic. Real providers should resolve token references through a secret manager.

Phase 4 knowledge endpoints include:

```text
POST/PATCH/GET /knowledge/sources
POST           /knowledge/sources/{source_id}/index
GET            /knowledge/index-jobs
POST           /knowledge/index-jobs/{job_id}/run
GET            /knowledge/search
POST           /knowledge/context
```

Knowledge indexing is exposed as a queue-and-run boundary for local development and deterministic tests. A source is not searchable until its versioned job succeeds. Search and context only return authorised current chunks; context additionally excludes sources that are not allowed for AI, stale sources by default, and content beyond the requested bounds.

Phase 5A work and continuity endpoints include:

```text
POST/GET/PATCH /work-items
GET            /work-items/{work_item_id}
POST           /work-items/{work_item_id}/transition
POST/GET       /work-items/{work_item_id}/reminders
POST           /reminders/{reminder_id}/acknowledge

POST/GET       /jobs
GET            /jobs/{job_id}
POST           /jobs/claim-next
POST           /jobs/reconcile-expired
POST           /jobs/{job_id}/heartbeat
POST           /jobs/{job_id}/complete
POST           /jobs/{job_id}/fail
POST           /jobs/{job_id}/retry
POST           /jobs/{job_id}/cancel

POST/GET       /workflows
GET            /workflows/{workflow_id}
POST           /workflows/{workflow_id}/advance
POST           /workflows/{workflow_id}/resume
```

The first typed workflow is `customer_follow_up`, with steps `review_context`, `create_commitment`, `await_approval`, and `complete`. Job handlers remain explicit application operations; generated code is not executed.

Phase 6A AI endpoints include:

```text
POST /ai/customer-summary
POST /ai/field-extraction
POST /ai/next-step-recommendation
POST /ai/communication-draft
POST /ai/workflow-plan
GET  /ai/providers/health
GET  /ai/runs
GET  /ai/runs/{run_id}
POST /ai/runs/{run_id}/feedback
```

The local AI provider is deterministic and does not call an external model. AI responses are reviewable data; workflow plans contain approval-gated typed proposals and never execute writes.

Phase 7A action endpoints include:

```text
GET  /actions/registry
POST /actions/dry-run
POST/GET /actions/proposals
GET  /actions/proposals/{proposal_id}
PATCH /actions/proposals/{proposal_id}
POST /actions/proposals/{proposal_id}/approve
POST /actions/proposals/{proposal_id}/reject
POST /actions/proposals/{proposal_id}/revoke
POST /actions/proposals/{proposal_id}/execute
POST /actions/proposals/expire
GET  /actions/executions
GET  /actions/executions/{execution_id}
POST /actions/executions/{execution_id}/retry
POST /actions/executions/{execution_id}/reconcile
```

Roles: `admin` has every permission; `manager` can approve, recover, write to integrations and see sensitive knowledge; `member` can read/write CRM data and propose/execute actions but not approve; `viewer` is read-only. A proposal cannot be approved by its requester or last editor (403 `separation_of_duties`, audited as denied).

The initial registry supports `task.create`, `contact.update`, `contact.assign_owner`, `activity.create`, `approval.request`, and fixture-backed `integration.activity.create`. Proposals remain separate from effects; external uncertain outcomes must be reconciled before retry.

Member administration endpoints (admin to manage, admin and manager to read):

```text
GET   /admin/members
POST  /admin/members            # add an existing user by email with a role
PATCH /admin/members/{membership_id}   # If-Match; change role or is_active
```

A tenant must keep at least one active admin; deactivated members lose access on their next request. With `SEED_DEMO_DATA=true`, `demo-tenant` has `demo-user` (admin) and `demo-manager` (manager), so one can propose an action and the other approve it:

```bash
MANAGER_TOKEN=$(uv run python -c 'from ai_crm.auth import create_access_token; print(create_access_token("demo-manager"))')
```

A permanent token-refresh failure marks a connection `needs_reauth`, which pauses syncs and writes and raises a proactive alert; a successful `test` or `refresh` restores it. The worker refreshes expired tokens before scheduling a sync.

Every response carries a W3C `traceparent` header. A valid inbound `traceparent` is continued (an invalid one is ignored and a new trace starts); the trace id is stored on operational events and durable jobs, so the worker's events for a job — including a webhook-triggered sync — share the originating request's trace. Query it with `GET /observability/events?trace_id=<32-hex>`. Provider adapters are not yet passed the trace id.

Phase 8A observability endpoints include:

```text
GET  /observability/summary
POST /observability/metrics/collect
GET  /observability/metrics
GET  /observability/events
GET  /observability/alerts
GET  /observability/alerts/{alert_id}
POST /observability/alerts/{alert_id}/acknowledge
POST /observability/alerts/{alert_id}/resolve
POST /observability/proactive-checks/run
```

Proactive checks create escalation work items for human review and suppress duplicate active alerts using transparent rule keys; they do not execute consequential actions automatically.

Phase 9A multi-agent coordination (registry, runs, delegation, human escalation) endpoints:

```text
GET/POST      /agents                     register (admin only) and list agents
GET/PATCH     /agents/{agent_id}          If-Match; status active|suspended|retired
POST/GET      /agent-runs                 start (Idempotency-Key) and list runs
GET           /agent-runs/{run_id}        run with its steps
POST          /agent-runs/{run_id}/steps  submit one step: retrieve|propose|delegate|escalate|output
POST          /agent-runs/{run_id}/pause|resume|cancel   If-Match
GET           /agent-runs/{run_id}/messages              persisted inter-agent messages
```

Agents are registered with an owner, version, capabilities (`read`, `propose`, `delegate`, `escalate`), a list of action types from the central action registry, a risk ceiling, a sensitive-data scope and token, step, side-effect, depth and fan-out limits (platform caps are set with the `AGENT_*` settings). There is no model loop yet: the run owner submits each step over the API, so runs are deterministic and replayable, and a model driver can plug in later. A step can only use existing paths: `retrieve` is permission-aware context assembly, and `propose` creates an ordinary action proposal that a human with `actions:approve` must approve (agents can never approve, execute or recover, and the run owner cannot approve their own agent's proposal). An agent's effective permissions are its owner's permissions narrowed to its capabilities, so it can never exceed its owner. Tokens are reported by the caller.

Delegation needs a reason, a target agent, an expected result, a deadline and a budget, and is rejected for cycles, depth, fan-out, duplicate ownership of an objective, a deadline past the parent's, or a budget above what the parent has left (the child budget is carved out of the parent's). Repeated failures of a target agent escalate instead of delegating again. Policy denials, conflicting proposals from two runs, budget exhaustion, repeated failures and missed deadlines create an `escalation` work item with the evidence and put the run in `waiting_human`; resuming needs that work item to be `completed`. The worker fails runs that pass their deadline, so a crashed driver cannot strand a run. 
Phase 9B coordination evaluation (admin runs it; anyone with `agents:read` can read results):

```text
GET  /agent-evals/scenarios
POST /agent-evals/run          {"scenario_key": optional, "replay_key": "..."}
GET  /agent-evals/results
GET  /agent-evals/compare?scenario_key=...&replay_key=...
```

Five fixed, replayable scenarios (`parallel_research`, `partial_failure`, `conflicting_data`, `duplicate_work`, `budget_pressure`) are scripted and replayed through the real coordination services as a single agent and as a delegating multi-agent team; the harness only creates proposals and never approves or executes. Each comparison reports task success, duplicate work, handoff latency, failed tool calls, human interventions, steps, tokens and cost (`AGENT_COST_PER_1K_TOKENS_MICROS`). Treat the results with care: no model is involved, so they measure the coordination machinery, not model quality; the human-baseline minutes and interventions are declared assumptions and are labelled as such in every response. On the current scenarios coordination costs extra steps and tokens (it is overhead on the clean path) and wins only on cross-run conflict detection; a single run does not flag two conflicting proposals of its own. Replaying the same `replay_key` returns the stored result.

### Operating the kill switches (Phase 10A)

Four capabilities can be switched off without a deploy: `ai`, `workflows`, `connectors` and `agents`. Each is on by default.

```text
GET /admin/feature-flags                      admin and manager
PUT /admin/feature-flags/{flag}               admin only; body {"enabled": false, "reason": "..."}
```

- **Disable one tenant:** `PUT` with `If-Match: "<version>"` (use `"0"` the first time; the response `ETag` is the next version). A reason is required when disabling. Every change is audited (`capability.disabled` / `capability.enabled`).
- **Disable every tenant:** set `DISABLED_CAPABILITIES=ai,agents` (comma-separated) and restart. A platform switch wins over a tenant flag and shows as `source: platform`.
- **What stops:** new work only. A blocked call returns `503` with code `capability_disabled` and writes a `capability.blocked` audit row. `ai` blocks every generating AI route; `workflows` blocks start/advance/resume; `connectors` blocks sync, test, refresh, external writes and incoming webhooks (so the provider retries) and keeps `integration.*` jobs queued instead of failing them; `agents` blocks starting runs, steps, resuming and evaluation runs.
- **What keeps working:** reads, AI feedback, disconnecting or revoking a connection, and pausing or cancelling agent runs, so a switched-off capability can always be wound down.
- **Re-enable:** `PUT` with `"enabled": true` and the current version, or remove the platform entry and restart. Queued connector jobs then run on the next worker tick.

This is the kill-switch part of Phase 10 only. SLOs, load and capacity evidence, retention and export, admin usage views and full runbooks are not built.

### SLOs, usage and runbooks (Phase 10B)

```text
GET /observability/slos      SLO status, value, target and owner (observability:read)
GET /admin/usage             per-tenant usage and capability state (admin and manager)
```

`GET /observability/slos` computes eight SLOs on demand from persisted data: oldest ready job age, job success rate, sync freshness, search freshness, action completion rate, AI fallback rate, AI latency and overdue agent runs. Each carries the owner from `SLO_OWNER` and a status of `met`, `breached`, `no_data` (nothing to measure, never reported as a pass) or `not_measured`. API availability, latency and error rate are listed but always `not_measured`, because the backend keeps no per-request telemetry; use your load balancer or APM for those. SLOs are evaluated when asked, so something external has to poll the endpoint for continuous monitoring. Targets live in `observability/slo.py` (the sync target follows `INTEGRATION_SYNC_INTERVAL_SECONDS`). An empty queue or zero overdue runs is a real measurement and reports `met`; rates with nothing to divide report `no_data`. Queue age includes running jobs whose lease has expired, so a crashed worker shows up. Windows are limited to 31 days.

`docs/runbooks/` has support procedures for failed jobs, syncs and actions, AI output problems, data-access issues, stuck agent runs and the kill switches. `tests/api/test_runbooks.py` checks that every endpoint a runbook names exists in the OpenAPI schema.

### Data lifecycle (Phase 10C)

```text
GET  /admin/audit-events          audit investigation, filterable, keyset-paginated (admin)
GET  /admin/export/{resource}     paginated JSON export of contacts, companies, opportunities, activities, tasks (admin)
POST /admin/retention/purge       purge aged telemetry; dry run by default (admin)
```

The purge deletes only operational events, metric observations, resolved alerts and published outbox rows older than `OBSERVABILITY_RETENTION_DAYS` (a lower cutoff is rejected), at most `RETENTION_PURGE_BATCH_SIZE` rows per table per call. Audit events and CRM records are never purged. Not built: deleting contacts or tenants, legal hold, archival, signed or asynchronous export files, and an automatic scheduled purge. Export is one JSON page per request in the same shape as the API read schemas (including `archived_at` and `version`); `OBSERVABILITY_RETENTION_DAYS` must now be at least 1; reading the audit log writes an `audit.queried` row, so polling it grows the audit table; members, connections and knowledge are not exported.

### Worker scaling (Phase 10D)

The worker rotates the tenant order every tick and gives each tenant at most `WORKER_BATCH_SIZE` jobs and `WORKER_TENANT_TIME_BUDGET_SECONDS` of job processing per tick (a running job always finishes; reconciliation, sync scheduling and proactive checks are not budgeted). A per-provider circuit breaker opens after `CONNECTOR_BREAKER_FAILURES` consecutive transient sync failures; while it is open (`CONNECTOR_BREAKER_COOLDOWN_SECONDS`) connector jobs stay queued without using an attempt, then a single job probes. Timeouts count as failures. `POST /jobs` and scheduled syncs are shed with `429 backpressure` and `Retry-After` once a tenant has `MAX_QUEUED_JOBS_PER_TENANT` queued or retryable jobs; the limit is soft (concurrent requests can overshoot it slightly), a repeated idempotency key still returns the original job, and webhook and reminder jobs are never dropped. Limits: breaker state lives in one worker process, so several workers each trip on their own; the job claim cannot filter by provider, so with more than one provider an outage pauses all connector jobs; there is no per-provider rate limiting; and none of this has been load tested.

Still open in Phase 10: load and capacity evidence, CI and an expand/contract migration policy.

## Checks

Run the project checks from this directory:

```bash
uv run ruff check .
uv run pytest -q
uv run alembic upgrade head
uv run alembic downgrade base
uv run --with pyright pyright
```

## Next backend slice

Backend Phase 9 is implemented and Phase 10 has kill switches, SLOs, an admin usage view and runbooks. The rest of Backend Phase 10 (capacity evidence, tenant-fair scheduling, CI, migration policy) is next. See `modules/backend/phase-10-scale-and-production-operations.md`.
