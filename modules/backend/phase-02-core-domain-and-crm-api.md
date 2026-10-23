# Backend Phase 02 — Core Domain and CRM API

## Goal

Implement the minimum customer and work domain required for the selected workflow, with stable APIs and explicit business invariants.

## Build in this phase

### B02.1 — CRM domain model

Implement only the records required by the validated workflow:

- People/contacts.
- Companies/accounts.
- Leads or opportunities.
- Conversations and activities.
- Notes and documents as references.
- Tasks and follow-ups.
- Ownership, tags, statuses, and custom fields where justified.

Define relationships, uniqueness, archival, ownership, lifecycle transitions, and source provenance.

### B02.2 — Domain services and invariants

- Keep state-transition rules in domain/application services, not controllers.
- Prevent invalid lifecycle transitions, duplicate activities, impossible due dates, and unauthorised ownership changes.
- Use transactions for changes that must remain consistent together.
- Emit domain events for material changes.

### B02.3 — Query and command APIs

- Define separate command and query paths where that improves clarity, without introducing full CQRS prematurely.
- Implement list/detail endpoints with cursor pagination where large lists are expected.
- Support filtering, sorting, search terms, field selection, and stable error responses.
- Add idempotency for retried create/import commands.

### B02.4 — Timeline and task APIs

- Return a customer timeline ordered by event time and ingestion time.
- Expose task queues, overdue work, ownership, dependencies, and completion evidence.
- Preserve source references for imported activities.

### B02.5 — API documentation and contract tests

- Publish the API contract with examples and permission notes.
- Add endpoint contract tests and consumer-facing fixtures.
- Treat breaking changes as versioned changes, not silent edits.

## Tests required

- Domain invariant and state-transition unit tests.
- Repository and migration integration tests.
- API validation, pagination, filtering, and error tests.
- Permission tests for every resource action.
- Idempotent create/import tests.
- End-to-end target-workflow test without AI.

## Exit criteria

- The target workflow can be completed manually using only backend APIs.
- Customer history, ownership, next steps, and overdue work are queryable.
- Record changes are transactional, audited, and attributable.
- API contracts are documented and tested.
- The backend can evolve without exposing ORM/provider details to clients.
