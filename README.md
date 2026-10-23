# AI CRM Backend

This is the runnable backend for the AI-first CRM and business automation platform described in `Target.md`.

## Current implementation: Backend Phases 1, 2, and 3A

The backend currently implements the runtime/security foundation, core CRM vertical slice, and a provider-neutral integration foundation:

- FastAPI application with versioned routes under `/api/v1`.
- SQLite with async SQLAlchemy for local development and a configurable database URL.
- Alembic migrations for the Phase 1, Phase 2, and Phase 3 schemas.
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

The next implementation is Backend Phase 4: permission-aware search, knowledge indexing, provenance, freshness, and bounded context retrieval. See `modules/backend/phase-04-search-knowledge-and-context.md`.
