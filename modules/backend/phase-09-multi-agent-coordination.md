# Backend Phase 09 — Multi-Agent Coordination

## Goal

Add multiple specialised agents only after the single-agent, action, workflow, and audit paths are stable. The backend must make responsibility, delegation, limits, and escalation explicit.

## Build in this phase

### B09.1 — Agent registry

- Store agent name, purpose, version, owner, allowed tools, data scope, risk level, and status.
- Define the agent's allowed read, propose, execute, delegate, and escalate capabilities.
- Prevent an agent from registering tools outside the central policy and action systems.

### B09.2 — Agent run and task model

- Persist agent runs, parent task, context references, tool calls, proposals, outputs, token/cost budgets, and terminal state.
- Correlate every agent run with the same work-item and action identifiers used by the rest of the backend.
- Make runs pauseable, cancellable, and inspectable.

### B09.3 — Delegation and supervision

- Require an explicit delegation reason, target agent, expected result, deadline, and budget.
- Bound delegation depth, fan-out, execution time, token usage, and external side effects.
- Detect cycles, duplicate ownership, conflicting proposals, and repeated failures.

### B09.4 — Human escalation

- Escalate uncertainty, policy denial, missing context, sensitive actions, conflicting agent outputs, and budget exhaustion.
- Create a human work item with the relevant evidence and proposed next steps.
- Resume only from an approved and current state.

### B09.5 — Coordination evaluation

- Compare multi-agent execution with a single-agent and human baseline.
- Measure task success, duplicate work, handoff latency, failed tool calls, human interventions, and cost.
- Keep replayable scenarios for partial failures and conflicting data.

## Tests required

- Agent permission and tool-boundary tests.
- Delegation cycle, depth, fan-out, and budget tests.
- Cancellation, pause/resume, and worker-crash tests.
- Conflicting recommendation and escalation tests.
- Duplicate-action and audit-chain tests.
- Multi-agent evaluation suite against the baseline.

## Exit criteria

- Every agent run has an owner, scope, version, budget, and terminal state.
- Agents cannot bypass retrieval, policy, approval, or action execution.
- Delegation is bounded and recoverable.
- Human escalation preserves context and responsibility.
- Multi-agent coordination demonstrates measurable value over a simpler alternative.

## Do not build yet

- Unbounded agent swarms.
- Autonomous high-impact actions.
- Agent communication that exists only in prompts and is not persisted.
