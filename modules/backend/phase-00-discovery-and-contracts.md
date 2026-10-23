# Backend Phase 00 — Discovery and Contracts

## Goal

Translate the validated product workflow into backend use cases, data ownership, API contracts, events, jobs, permissions, and measurable non-functional requirements.

## Build in this phase

### B00.1 — Use-case catalogue

Document the exact commands and queries needed by the initial workflow. For each use case, define:

- Actor and tenant.
- Preconditions and required permissions.
- Input and output.
- State changes.
- External effects.
- Failure and retry behaviour.
- Audit and metric events.

Examples include creating a customer, importing an activity, assigning a follow-up, retrieving customer context, generating a draft, approving a proposed update, and executing a low-risk external action.

### B00.2 — Domain boundaries and ownership

- Decide which backend module owns each entity and business rule.
- Identify references between modules without allowing uncontrolled direct table access.
- Define which data is authoritative internally and which data remains owned by an external provider.
- Record decisions in small architecture decision records.

### B00.3 — API and event contracts

- Choose the initial API style based on the actual clients; use a documented versioned HTTP API unless requirements justify another style.
- Define resource names, request/response schemas, pagination, filtering, errors, idempotency headers, and authentication behaviour.
- Define domain events and integration events separately.
- Define compatibility and deprecation rules.

### B00.4 — Non-functional requirements

Set initial targets for:

- API latency and throughput.
- Background-job completion time.
- Search freshness.
- Integration recovery time.
- AI response timeout and cost limits.
- Audit completeness.
- Availability and data-retention expectations.

### B00.5 — Test fixtures and evaluation cases

- Create anonymised tenants, users, customers, activities, documents, failures, and permissions.
- Create representative happy-path, incomplete-data, conflicting-data, stale-data, and denied-access cases.
- Define baseline data for the target workflow.

## Deliverables

- Backend use-case catalogue.
- Module ownership map.
- Initial API specification and error model.
- Event and job catalogue.
- Permission matrix.
- Non-functional requirements and test fixtures.

## Exit criteria

- Every MVP capability maps to a named backend use case.
- Every use case has an owner, permission rule, failure path, and audit event.
- No module depends on an undefined shared table or undocumented provider behaviour.
- The team can generate or review API documentation from the contracts.
- The chosen architecture is simple enough for the current team and load assumptions.

## Do not build yet

- Generic service decomposition.
- A large event bus or workflow DSL.
- AI prompts before context and output contracts are defined.
