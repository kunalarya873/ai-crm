# AI CRM Backend

This is the runnable backend for the AI-first CRM and business automation platform described in `Target.md`.

## Current implementation: Backend Phases 1, 2, 3A, 4, 5A, 6A, 7A, and 8A

The backend currently implements the runtime/security foundation, core CRM vertical slice, provider-neutral integration foundation, permission-aware knowledge retrieval, durable work execution, grounded AI requests, approval-gated action execution, and operational measurement:

- FastAPI application with versioned routes under `/api/v1`.
- SQLite with async SQLAlchemy for local development and a configurable database URL.
- Alembic migrations for the Phase 1 through Phase 8A schemas.
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

The initial registry supports `task.create`, `contact.update`, `contact.assign_owner`, `activity.create`, `approval.request`, and fixture-backed `integration.activity.create`. Proposals remain separate from effects; external uncertain outcomes must be reconciled before retry.

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

The next implementation is Backend Phase 9: multi-agent coordination. See `modules/backend/phase-09-multi-agent-coordination.md`.
