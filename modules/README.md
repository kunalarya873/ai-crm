# AI-First CRM and Business Automation Platform — Development Modules

This directory converts [`../Target.md`](../Target.md) into a development sequence. Each phase is intentionally separated into its own file so that the product can be built and reviewed incrementally.

## Product strategy

The product should not begin as a generic CRM with an AI chatbot. The first release must prove a narrower hypothesis:

> A unified, permission-aware workspace can help a defined business team understand customer context, complete routine follow-up work, and inspect every AI-assisted action more reliably than the team's current collection of tools.

The development order therefore prioritises:

1. Customer and workflow validation before major implementation.
2. Reliable data, permissions, auditability, and integrations before autonomous AI.
3. A focused CRM workflow before broad CRM feature parity.
4. Human-reviewed AI actions before autonomous actions.
5. Measurable business outcomes before expanding the feature surface.

## Phase order

| Phase | File | Purpose | Release position |
|---|---|---|---|
| 0 | [Discovery and validation](phase-00-discovery-and-validation.md) | Validate the target customer, workflow, and market gap | Before product build |
| 1 | [Foundation and security](phase-01-foundation-and-security.md) | Establish the application, tenant, identity, data, and audit foundations | Platform baseline |
| 2 | [Core CRM](phase-02-core-crm.md) | Build the minimum useful customer and work records | MVP foundation |
| 3 | [Integrations and unified context](phase-03-integrations-and-unified-context.md) | Connect authorised systems and create a canonical business context | MVP foundation |
| 4 | [Knowledge and search](phase-04-knowledge-and-search.md) | Make customer and organisational information discoverable and traceable | MVP foundation |
| 5 | [Work management and continuity](phase-05-work-management-and-continuity.md) | Preserve commitments, ownership, handoffs, and follow-ups | MVP foundation |
| 6 | [AI copilot](phase-06-ai-copilot.md) | Add grounded summaries, recommendations, and drafts with human review | MVP capability |
| 7 | [Governed actions and starter automation](phase-07-governed-actions-and-automation.md) | Turn approved intent into reliable, observable actions | MVP completion |
| 8 | [Proactive insights and measurement](phase-08-proactive-insights-and-measurement.md) | Detect exceptions and measure business value | Post-MVP growth |
| 9 | [Multi-agent coordination](phase-09-multi-agent-coordination.md) | Coordinate specialised agents with explicit ownership and escalation | Advanced capability |
| 10 | [Enterprise readiness and scale](phase-10-enterprise-readiness-and-scale.md) | Support larger organisations, stronger controls, and reliable scale | Enterprise maturity |

## Backend implementation roadmap

The product phases above describe what the product must achieve. The backend implementation sequence is documented separately in [`backend/README.md`](backend/README.md), including API contracts, domain modules, persistence, jobs, integrations, AI gateways, action execution, observability, and production operations.

## Recommended MVP boundary

The MVP should be released after Phase 7, but with deliberately narrow scope:

- One clearly defined customer segment and one primary business workflow.
- One tenant model with role-based access control.
- Core records: people, companies, leads/opportunities, conversations, tasks, notes, and documents.
- Two or three integrations selected from customer research, not an arbitrary integration catalogue.
- Unified search and customer context with citations back to source records.
- AI assistance for summaries, information extraction, next-step recommendations, and communication drafts.
- Approval-gated actions for record updates, task creation, and one low-risk external action.
- Execution history, audit events, failure states, retries, and an operator-readable explanation of each action.
- Measurement of time saved, task completion, human edits, failures, AI cost, and business outcome proxies.

Do not include autonomous multi-agent behaviour, unrestricted outbound communication, financial actions, broad CRM parity, or a fully general natural-language workflow builder in the first release.

## Cross-cutting requirements for every phase

- **Security:** tenant isolation, least-privilege permissions, secret protection, secure defaults, and sensitive-data handling.
- **Reliability:** idempotency for external writes, timeouts, retries with limits, dead-letter or manual-recovery states, and clear failure messages.
- **Observability:** structured logs, metrics, traces where useful, correlation IDs, and operational dashboards.
- **AI accountability:** record the model/tool version, input context references, proposed action, approval, execution result, and human intervention.
- **Testing:** unit tests, integration tests for external boundaries, permission tests, failure-path tests, and representative user-journey tests.
- **Evaluation:** distinguish observed data from AI-generated recommendations or predictions; retain evidence for important outputs.
- **Product validation:** every phase must have a user-facing hypothesis and a measurable exit condition.

## Dependency rule

Do not start a later phase merely because its UI can be prototyped. A phase may be prototyped early, but production implementation should wait until its dependencies and exit criteria are met. In particular:

- AI actions depend on trustworthy records, permissions, and audit events.
- Cross-application writes depend on idempotency, retries, and connector error handling.
- Proactive insights depend on event history and baseline metrics.
- Multi-agent coordination depends on a stable action model, ownership model, and escalation path.

## Requirement coverage

| Target.md concern | Primary phases |
|---|---|
| Fragmented customer and business information | 2, 3, 4 |
| Knowledge retrieval and organisational knowledge | 3, 4 |
| Repetitive administrative work and communication | 5, 6 |
| Customer management and prioritisation | 2, 5, 6, 8 |
| Natural-language intent to reliable actions | 6, 7 |
| Accessible workflow automation | 7 |
| Cross-application reliability | 3, 7, 10 |
| Operational continuity and handoffs | 5, 7 |
| Proactive issue detection | 8 |
| Performance and measurable AI value | 8 |
| AI accountability, control, and cost | 1, 7, 8, 10 |
| Adaptability to different business contexts | 1, 3, 4, 10 |
| Multiple-agent coordination | 9 |
