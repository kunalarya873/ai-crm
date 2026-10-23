# Backend Phase 07 — Action Execution and Automation

## Goal

Convert approved business intent into reliable internal or external effects through a typed, policy-checked, idempotent action runtime.

## Build in this phase

### B07.1 — Action contract and registry

For every action define:

- Action type and version.
- Input schema and validation.
- Required permissions and approval policy.
- Risk level and affected resources.
- Idempotency strategy.
- Timeout, retry, and compensation/recovery behaviour.
- Audit and metric events.

Start with low-risk actions such as create task, update a permitted CRM field, add a note, assign an owner, or create an approval request.

### B07.2 — Proposal and approval service

- Store proposed actions separately from executed actions.
- Include evidence, intended changes, affected records, actor, risk, expiration, and expected side effects.
- Support approve, reject, edit, expire, revoke, and delegate states.
- Re-check permissions and record versions at approval and execution time.

### B07.3 — Action executor

- Execute actions through one controlled application service.
- Use idempotency keys and effect records to prevent duplicates.
- Apply timeouts, bounded retries, concurrency checks, and provider-specific error mapping.
- Persist requested, approved, started, completed, failed, cancelled, and recovered states.

### B07.4 — Workflow triggers and templates

- Implement explicit event, schedule, and manual triggers.
- Use typed conditions and action steps.
- Provide dry-run and test-data execution.
- Keep generated workflow plans in proposal state until a user or policy approves them.

### B07.5 — Recovery and reconciliation

- Provide failed-action queues, manual retry, operator notes, and safe replay.
- Reconcile uncertain external outcomes before retrying.
- Use compensating actions only where they are defined and safe; do not claim universal rollback.

## Tests required

- Approval-policy and reauthorisation tests.
- Idempotency and duplicate-delivery tests.
- Record-version/concurrency conflict tests.
- External timeout, partial success, rate-limit, and uncertain-outcome tests.
- Workflow dry-run and resume tests.
- Audit trail completeness tests.

## Exit criteria

- No action bypasses policy and approval requirements.
- Duplicate requests cannot cause duplicate side effects.
- Every action has a visible final or recoverable state.
- Operators can understand and safely recover failures.
- The target workflow completes from request to verified outcome using backend APIs and jobs.
