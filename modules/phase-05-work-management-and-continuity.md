# Phase 05 — Work Management and Operational Continuity

## Goal

Connect customer context to the work people must complete. The product should preserve commitments across time, people, and applications instead of treating every interaction as a separate conversation.

## Modules

### M05.1 — Work item lifecycle

- Define task, follow-up, review, approval, and handoff states.
- Support owner, watchers, due dates, dependencies, priority, reason, and completion evidence.
- Define cancellation, reassignment, escalation, and overdue behaviour.

### M05.2 — Handoffs and responsibility

- Make the responsible person and next action explicit.
- Preserve context when a task moves between teams or owners.
- Record acceptance, rejection, reassignment, and escalation events.

### M05.3 — Commitments and continuity

- Extract or record commitments from meetings, conversations, notes, and workflows.
- Link commitments to the customer, source evidence, owner, due date, and outcome.
- Surface outstanding commitments in customer and personal work views.

### M05.4 — Work queues and operational views

- Provide personal, team, overdue, approval, and exception queues.
- Support prioritisation by urgency, customer impact, business value, and dependency.
- Show why a work item is present and what evidence supports its priority.

### M05.5 — Notifications and reminders

- Add configurable in-app and selected external notifications.
- Avoid duplicate or noisy reminders.
- Make notification delivery and acknowledgement observable.

## Deliverables

- Work-item state model and APIs.
- Handoff and escalation flows.
- Commitment tracking linked to source evidence.
- Personal/team work queues.
- Notification and reminder controls.

## Dependencies

Phases 01–04 and the workflow definition from Phase 00.

## Exit criteria

- A multi-step workflow can move between users without losing context or ownership.
- Overdue and blocked work is visible without manual record-by-record inspection.
- Every commitment has a source, owner, status, and next step or explicit closure.
- Notifications are permission-aware, deduplicated, and auditable.
- A user can complete the target workflow without copying context between tools.

## Do not build yet

- Fully autonomous task creation from every conversation.
- Complex project management features unrelated to the selected workflow.
