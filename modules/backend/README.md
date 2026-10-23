# Backend Development Plan

This directory explains how to implement the backend for the AI-first CRM and business automation platform described in [`../../Target.md`](../../Target.md) and phased in [`../README.md`](../README.md).

The backend should be developed as a **modular monolith first**: one deployable backend with strict internal module boundaries, one authoritative data model, and asynchronous workers for long-running or external work. Split into separately deployed services only when measured scale, isolation, or ownership requires it.

## Backend objective

The backend must make business work dependable before it makes it autonomous. It owns:

- Tenant-aware customer and business records.
- Permission-checked APIs and data access.
- Integrations and synchronisation with external applications.
- Searchable, traceable business context.
- Tasks, commitments, approvals, and workflows.
- AI requests, evidence, usage, and evaluation records.
- Typed actions with idempotent, observable execution.
- Audit history, operational events, metrics, and recovery paths.

## Backend phase order

| Backend phase | File | Main outcome |
|---|---|---|
| 0 | [Discovery and contracts](phase-00-discovery-and-contracts.md) | Backend use cases, boundaries, contracts, and non-functional requirements |
| 1 | [Runtime, security, and data foundation](phase-01-runtime-security-and-data-foundation.md) | Secure application shell, tenancy, authentication, authorisation, migrations, and audit |
| 2 | [Core domain and CRM API](phase-02-core-domain-and-crm-api.md) | Customer records, activities, pipeline, tasks, and stable APIs |
| 3 | [Integrations and synchronisation](phase-03-integrations-and-sync.md) | Connector ports, provider adapters, webhooks, sync jobs, and recovery |
| 4 | [Search, knowledge, and context](phase-04-search-knowledge-and-context.md) | Permission-aware retrieval and canonical AI/business context |
| 5 | [Workflows, jobs, and continuity](phase-05-workflows-jobs-and-continuity.md) | Durable work items, commitments, queues, scheduling, and workflow state |
| 6 | [AI gateway and copilot backend](phase-06-ai-gateway-and-copilot.md) | Grounded AI requests, structured output, cost tracking, and evaluations |
| 7 | [Action execution and automation](phase-07-action-execution-and-automation.md) | Approval-gated, idempotent, recoverable internal and external actions |
| 8 | [Observability, measurement, and proactive jobs](phase-08-observability-measurement-and-proactive-jobs.md) | Operational metrics, value measurement, alerts, and exception detection |
| 9 | [Multi-agent coordination](phase-09-multi-agent-coordination.md) | Bounded agents, delegation, escalation, budgets, and supervision |
| 10 | [Scale and production operations](phase-10-scale-and-production-operations.md) | SLOs, performance, data lifecycle, deployment, support, and enterprise readiness |

## Recommended backend module boundaries

Keep these as internal modules even if they share one process and database:

1. `identity` — users, organisations, memberships, roles, sessions, and invitations.
2. `policy` — permission checks, scopes, action risk policies, and access decisions.
3. `crm` — people, companies, leads, opportunities, activities, notes, and customer timelines.
4. `work` — tasks, commitments, handoffs, approvals, reminders, and escalations.
5. `integration` — connector configuration, credentials, provider adapters, sync state, and webhooks.
6. `knowledge` — documents, indexing, search, retrieval, provenance, and freshness.
7. `ai` — model gateway, prompt versions, context assembly, generation records, and evaluations.
8. `automation` — triggers, workflow definitions, action proposals, action execution, and recovery.
9. `analytics` — operational events, metrics, outcome attribution, and anomaly jobs.
10. `audit` — append-only actor/action history and investigation queries.
11. `platform` — configuration, health checks, jobs, notifications, rate limits, and shared infrastructure.

## Standard request flow

```text
HTTP/API request
  -> authentication and tenant resolution
  -> input validation and permission policy
  -> application service / use case
  -> domain rules and transaction
  -> repository and outbox event
  -> response or asynchronous job status

Worker/job
  -> claim job with lease
  -> execute connector, AI, indexing, or workflow step
  -> retry safely or record recoverable failure
  -> emit audit, metric, and domain events
```

Do not put business rules directly in controllers, route handlers, ORM models, connector adapters, or AI prompts. Controllers translate transport data; application services coordinate a use case; domain code enforces invariants; repositories persist; workers execute asynchronous work.

## How to develop each backend module

For every feature, follow this order:

1. Write the user-facing use case and explicit non-goals.
2. Define the API contract and error cases.
3. Define data ownership, invariants, permission checks, and state transitions.
4. Implement the application service/use case.
5. Implement persistence and migrations.
6. Add domain/outbox events and background work where required.
7. Add unit, integration, permission, failure-path, and contract tests.
8. Add structured logs, metrics, audit events, and correlation IDs.
9. Document the endpoint, event, job, operational recovery, and rollout flag.
10. Verify the phase exit criteria before starting dependent work.

## Backend MVP completion state

At the end of backend Phase 7, the backend should support one validated workflow end-to-end:

- An authorised user can read and update customer records.
- Selected external records are synchronised with provenance and freshness.
- Search and context retrieval enforce permissions and return evidence.
- Tasks and commitments preserve ownership and next steps.
- AI can summarise, extract, recommend, or draft without directly changing external systems.
- Approved proposals become typed actions.
- Actions are idempotent, audited, retryable, and recoverable.
- Operators can inspect failed syncs, AI runs, approvals, and action executions.

## Backend rules from day one

- Prefer a modular monolith over premature microservices.
- Use a relational source of truth for transactional CRM and workflow data unless research proves otherwise.
- Use asynchronous jobs for external APIs, AI calls, indexing, notifications, and long-running workflows.
- Treat every external write as at-least-once delivery and make the operation idempotent.
- Apply tenant and permission filters at the repository/query boundary and again before external action execution.
- Version public API contracts, event schemas, prompts, and action definitions.
- Never treat an AI response as a trusted command; convert it into validated, reviewable domain data.
- Keep provider-specific integration details behind adapters.
- Make manual recovery possible for every asynchronous operation.
