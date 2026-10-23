# Backend Phase 01 — Runtime, Security, and Data Foundation

## Goal

Build a secure, repeatable backend runtime before implementing customer data or AI behaviour.

## Build in this phase

### B01.1 — Application shell

- Establish the backend entry point, configuration loading, environment validation, dependency injection, and graceful shutdown.
- Separate HTTP/API handling, background workers, scheduled jobs, and migrations.
- Add health, readiness, and version endpoints.
- Add a consistent request context containing correlation ID, actor, tenant, locale, and deadline.

### B01.2 — Persistence and migrations

- Select and configure the transactional database.
- Add migration tooling, connection pooling, transaction helpers, and seed fixtures.
- Define timestamps, identifiers, soft-delete/archive behaviour, optimistic concurrency, and data ownership conventions.
- Ensure migrations are forward-safe and tested from an empty database.

### B01.3 — Authentication and tenancy

- Implement user identity, organisation/tenant membership, session/token validation, and invitations.
- Resolve the tenant for every request and background job.
- Enforce tenant isolation in queries and service methods.
- Store secrets and provider tokens outside source control and ordinary logs.

### B01.4 — Authorisation and policy

- Implement role/permission checks for read, create, update, delete, export, approve, and execute operations.
- Centralise policy decisions so the same rules apply to APIs, jobs, search, AI retrieval, and action execution.
- Return safe denial errors without leaking protected record existence.

### B01.5 — Audit, errors, and platform events

- Add append-only audit events with actor, tenant, operation, target, reason, correlation ID, and outcome.
- Standardise validation, authentication, authorisation, conflict, not-found, rate-limit, dependency, and internal errors.
- Add an outbox/event table or equivalent reliable publication mechanism.

## Tests required

- Migration-from-empty and migration-upgrade tests.
- Tenant isolation tests.
- Permission allow/deny tests.
- Authentication/session expiry tests.
- Audit completeness tests.
- Malformed input and safe error-response tests.
- Health/readiness tests.

## Exit criteria

- A clean environment can start the API, database, worker, and test suite using documented commands.
- No request or job runs without an actor/tenant context or an explicit system identity.
- Cross-tenant reads and writes are blocked.
- Every privileged operation produces an audit event.
- Secrets, tokens, and sensitive payloads are not emitted in logs.
