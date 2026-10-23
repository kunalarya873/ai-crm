# Phase 07 — Governed Actions and Starter Automation

## Goal

Close the gap between business intent and completed work by turning reviewed proposals into reliable, permission-checked actions. This phase completes the narrow MVP.

## Modules

### M07.1 — Action catalog

- Define typed actions such as create task, update a field, add a note, assign an owner, create an approval request, or send a reviewed message.
- Specify inputs, required permissions, risk level, validation, idempotency key, and rollback or recovery behaviour.
- Keep internal and external actions distinct.

### M07.2 — Proposal and approval flow

- Represent an AI or workflow proposal before execution.
- Show intended changes, evidence, permissions, risk, affected records, and expected side effects.
- Support approve, reject, edit, expire, delegate, and revoke states.

### M07.3 — Action executor

- Execute approved actions through a controlled service boundary.
- Apply validation, authorisation, concurrency checks, timeout, retry, and duplicate prevention.
- Store requested, approved, started, completed, failed, and recovered states.

### M07.4 — Starter workflow engine

- Support a small set of explicit triggers, conditions, actions, delays, and approval steps.
- Begin with templates for the validated workflow instead of a fully general builder.
- Provide dry-run and test-data execution.

### M07.5 — Natural-language workflow proposal

- Allow a user to describe a desired outcome in natural language.
- Convert the request into a reviewable workflow plan, not immediate execution.
- Highlight assumptions, missing fields, risky steps, and required approvals.

### M07.6 — Recovery and operations

- Add retry controls, manual recovery, dead-letter/failed states, and operator notes.
- Explain failures in business language while retaining technical details for operators.
- Support replay only when idempotency and safety conditions are satisfied.

## Deliverables

- Typed action contract and action catalogue.
- Approval and proposal UI.
- Reliable executor with audit trail.
- Narrow workflow engine and validated workflow templates.
- Dry-run, failure recovery, and operator controls.

## Dependencies

Phases 01–06. Integration write paths must be tested before external actions are enabled.

## Exit criteria

- No action runs without the required permission and approval state.
- Repeated requests cannot create duplicate external effects.
- Failed actions are visible, recoverable, and do not silently appear successful.
- Users can understand what an AI or workflow proposed and what actually happened.
- The target workflow completes end-to-end with measurable reduction in manual effort.

## MVP release gate

Release to a controlled pilot only when:

- The Phase 00 baseline can be compared with product results.
- Security, permission, retrieval, action, and failure-path tests pass.
- Pilot users can disable or override AI assistance and continue manually.
- Support/operations ownership exists for failed syncs, failed actions, and unsafe outputs.

## Do not build yet

- Financial transactions, irreversible destructive actions, or unrestricted outbound communication.
- Fully general workflow generation without templates, policy checks, and testing.
- Multi-agent delegation.
