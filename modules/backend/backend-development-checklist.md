# Backend Feature Development Checklist

Use this checklist for every backend feature or module.

## Before coding

- [ ] Identify the user and business outcome.
- [ ] Write the use case and non-goals.
- [ ] Identify the owning backend module.
- [ ] Define actors, tenant scope, and permissions.
- [ ] Define input, output, state transitions, and failure states.
- [ ] Decide whether work is synchronous, asynchronous, scheduled, or event-driven.
- [ ] Define idempotency and concurrency behaviour.
- [ ] Define audit events, metrics, and operational alerts.

## While coding

- [ ] Validate input at the API boundary.
- [ ] Keep business rules in application/domain services.
- [ ] Keep database access behind repositories or data-access modules.
- [ ] Keep provider SDKs behind integration adapters.
- [ ] Use transactions for related state changes.
- [ ] Publish reliable outbox/domain events when other work depends on a change.
- [ ] Add timeouts and bounded retries to external calls.
- [ ] Never log secrets or unnecessary sensitive payloads.
- [ ] Add feature flags for risky or experimental behaviour.

## Tests before merge

- [ ] Unit tests for business rules and edge cases.
- [ ] Repository/database integration tests.
- [ ] API contract and validation tests.
- [ ] Tenant isolation and permission tests.
- [ ] Idempotency and duplicate-delivery tests.
- [ ] Timeout, retry, partial failure, and recovery tests.
- [ ] Representative end-to-end workflow test.
- [ ] AI evaluation tests if AI is involved.

## Before release

- [ ] Migration is safe and reversible or has a documented recovery plan.
- [ ] Metrics and logs can identify failures by tenant, operation, and correlation ID.
- [ ] Runbook explains how to inspect and recover failures.
- [ ] API/event/prompt/action versions are recorded.
- [ ] Rollout and rollback/disable plans exist.
- [ ] Documentation and API examples are updated.
- [ ] Phase exit criteria have evidence.
