# Development Gates and Definition of Done

## Gate A — Research readiness

Before implementation begins, the team has a target user, a primary workflow, a baseline, an evaluation set, and a list of unacceptable risks.

## Gate B — Platform readiness

Before customer data or AI is introduced, tenant isolation, permissions, audit events, secrets, error handling, and repeatable tests work in a clean environment.

## Gate C — Workflow readiness

Before AI is introduced, the complete target workflow can be completed manually in the product and its failure states are understood.

## Gate D — AI readiness

Before generated output is used operationally, retrieval is permission-aware, evidence is visible, quality is evaluated, costs are measured, and manual review is available.

## Gate E — Action readiness

Before any external write is enabled, the action is typed, permission-checked, approval-gated where required, idempotent, observable, retry-safe, and recoverable.

## Gate F — Pilot readiness

Before a pilot, the team has a rollback/disable plan, support owner, incident path, privacy review, representative test cases, and a way to compare results with the Phase 00 baseline.

## Gate G — Expansion readiness

Before adding more integrations, workflows, agents, or customer segments, the current capability has evidence of value, acceptable reliability, manageable support cost, and no unresolved high-severity governance issue.

## Definition of done for every module

- Scope and non-goals are documented.
- Data and permission behaviour are defined.
- Happy-path and failure-path tests exist.
- Audit and observability events are present.
- User-facing errors explain the next available action.
- Metrics and evaluation criteria are defined.
- Documentation and operating notes are updated.
- The phase exit criteria are checked with evidence, not assumed.
