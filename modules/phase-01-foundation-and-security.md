# Phase 01 — Foundation and Security

## Goal

Create a secure, testable, observable platform foundation that can support CRM records, integrations, AI calls, approvals, and auditability without forcing premature microservice complexity.

## Modules

### M01.1 — Application and environment foundation

- Establish the repository structure, local development workflow, configuration conventions, and environment separation.
- Define API, background-job, and frontend boundaries.
- Add database migrations, seed data, health checks, and a repeatable test command.
- Define feature flags for experimental AI and automation capabilities.

### M01.2 — Tenant and identity model

- Implement organisations/tenants, users, teams, roles, and invitations.
- Establish tenant isolation at the data-access and API layers.
- Support session management and a standard authentication boundary.
- Record actor identity for user, service, workflow, and AI-initiated operations.

### M01.3 — Authorisation and policy engine

- Define permissions for reading, creating, updating, deleting, exporting, approving, and executing actions.
- Apply least privilege to records, integrations, documents, and AI tools.
- Make policy decisions inspectable for operators.
- Add tests for cross-tenant access, role boundaries, and denied actions.

### M01.4 — Audit, observability, and secrets

- Create append-only audit events for authentication, access changes, record changes, approvals, AI requests, and external actions.
- Add correlation IDs across requests, jobs, connector calls, and AI runs.
- Protect credentials and integration tokens using the environment's secret-management approach.
- Add error reporting, structured logs, basic metrics, and a minimal operator view.

### M01.5 — Core data and API conventions

- Define identifiers, timestamps, soft-delete/archive rules, pagination, filtering, validation, and error formats.
- Establish a canonical event or activity model that later modules can extend.
- Document API versioning and compatibility expectations.

## Deliverables

- Running application skeleton with local setup instructions.
- Tenant-aware persistence and authorisation.
- Audit-event schema and searchable audit records.
- Secure configuration and secret-handling approach.
- Initial API/data conventions and automated checks.

## Dependencies

Phase 00 defines the target workflow and the minimum roles/actions it needs.

## Exit criteria

- A test user can create an organisation, invite another user, and receive only permitted data.
- A denied cross-tenant or unauthorised action is blocked and audited.
- A request can be traced from API entry through background work.
- Secrets are not stored in source control, logs, or ordinary database records.
- Database migrations and the smallest meaningful test suite run from a clean environment.

## Do not build yet

- Fine-grained enterprise hierarchy beyond the validated use case.
- Complex event sourcing or microservices unless a real constraint requires it.
- Autonomous AI actions.
