# Phase 09 — Multi-Agent Coordination

## Goal

Introduce specialised AI capabilities only after the product has stable context, action, approval, ownership, and measurement primitives. Agents should reduce duplication rather than hide responsibility.

## Modules

### M09.1 — Agent registry and responsibility boundaries

- Register agents with purpose, capabilities, tools, data scopes, risk level, owner, and version.
- Define what each agent may decide, propose, execute, delegate, or escalate.
- Prevent overlapping ownership where it would cause duplicate work.

### M09.2 — Shared task and context protocol

- Standardise the context passed to agents, including source references, freshness, permissions, and prior work.
- Use shared work-item and action identifiers for correlation.
- Prevent agents from bypassing the canonical action and audit path.

### M09.3 — Delegation and escalation

- Support explicit delegation with a reason, expected output, deadline, and owner.
- Escalate uncertainty, permission limits, conflicting recommendations, and repeated failures to a human or supervising process.
- Prevent circular delegation and uncontrolled agent fan-out.

### M09.4 — Agent evaluation and coordination metrics

- Measure duplicate work, delegation depth, handoff latency, tool failures, human interventions, and task success.
- Evaluate whether a multi-agent flow is better than a single-agent or human workflow.
- Maintain replayable test scenarios for conflicts and partial failures.

### M09.5 — Supervisory controls

- Provide pause, disable, revoke, and version rollback controls.
- Expose the full chain of agent proposals, decisions, actions, and escalations.
- Apply budgets for tokens, execution time, tool calls, and external effects.

## Deliverables

- Agent registry and capability model.
- Shared context and work protocol.
- Delegation, escalation, and supervision controls.
- Multi-agent evaluation suite and operational metrics.

## Dependencies

Phases 01, 03, 04, 05, 06, 07, and 08. In particular, the action catalogue and audit trail must already be reliable.

## Exit criteria

- Every agent has a named responsibility, owner, version, and permission boundary.
- Delegation is bounded, observable, and recoverable.
- Agents cannot create duplicate or unauthorised actions by bypassing the action executor.
- Human escalation is clear and preserves the relevant context.
- A measured pilot shows that coordination improves an identified outcome.

## Do not build yet

- A swarm of loosely defined agents.
- Autonomous delegation with no budget, owner, or stop condition.
- Agent-to-agent communication that is not recorded in the operational history.
