# Backend Phase 05 — Workflows, Jobs, and Operational Continuity

## Goal

Make multi-step business work durable. A request that spans people, time, applications, or AI calls must have a stored state, an owner, a retry policy, and a recovery path.

## Build in this phase

### B05.1 — Work-item domain

- Implement tasks, commitments, handoffs, approvals, reminders, and escalations.
- Define states, transitions, ownership, due dates, dependencies, priorities, and completion evidence.
- Reject invalid transitions and record every transition.

### B05.2 — Job execution platform

- Add a durable job queue or equivalent worker mechanism.
- Implement job identity, queue, priority, lease, heartbeat, timeout, retry count, backoff, and dead-letter/manual-recovery state.
- Make job handlers idempotent and safe after worker crashes.

### B05.3 — Scheduling and reminders

- Support delayed work, due-date reminders, recurring checks, and escalation timers.
- Define timezone and daylight-saving behaviour.
- Deduplicate notifications and record delivery/acknowledgement.

### B05.4 — Workflow state machine

- Implement explicit workflow definitions for the validated use case.
- Store workflow instance state, current step, input references, outputs, approvals, and errors.
- Keep workflow steps typed and bounded; do not execute arbitrary generated code.

### B05.5 — Handoffs and continuity queries

- Expose outstanding commitments, blocked items, upcoming deadlines, and prior context.
- Preserve evidence when work moves between users or teams.
- Support safe reassignment and escalation.

## Tests required

- Job retry, timeout, lease expiry, duplicate delivery, and worker-crash tests.
- Workflow state-transition and resume tests.
- Scheduler timezone and deduplication tests.
- Permission tests for team queues and handoffs.
- End-to-end multi-step workflow tests with partial failure.

## Exit criteria

- A workflow can pause and resume without losing state or context.
- A crashed or duplicated worker does not create duplicate outcomes.
- Operators can inspect, retry, cancel, or recover failed jobs safely.
- Users can query overdue, blocked, assigned, and unowned work.
- No later AI or automation feature needs to keep workflow state only in memory.
