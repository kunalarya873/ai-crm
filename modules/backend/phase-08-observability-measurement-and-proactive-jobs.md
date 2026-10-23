# Backend Phase 08 — Observability, Measurement, and Proactive Jobs

## Goal

Give the backend the evidence needed to operate the product, detect meaningful business exceptions, and measure whether AI and automation create value.

## Build in this phase

### B08.1 — Operational telemetry

- Emit structured logs with tenant, actor, operation, correlation ID, resource, job, provider, and outcome fields.
- Add request, job, sync, search, AI, action, and workflow metrics.
- Propagate trace context across API requests, workers, connector calls, and AI providers.
- Redact or hash sensitive fields before telemetry leaves the application.

### B08.2 — Business event model

- Record events for customer changes, activities, tasks, commitments, approvals, syncs, AI runs, actions, errors, and outcomes.
- Define event versions, retention, deduplication, and ownership.
- Use events to support reporting without making dashboards depend on fragile live joins alone.

### B08.3 — Measurement APIs

- Expose metrics for response time, follow-up completion, overdue work, failure rate, human intervention, AI usage, cost, and outcome proxies.
- Allow drill-down from an aggregate metric to authorised source records.
- Mark incomplete, delayed, estimated, or model-generated values.

### B08.4 — Proactive exception jobs

- Begin with transparent rules for overdue commitments, inactive opportunities, repeated sync/action failures, delayed responses, and missing data.
- Run detection as bounded scheduled jobs or event-triggered checks.
- Deduplicate and suppress repeated alerts.
- Create reviewable work items rather than taking consequential action automatically.

### B08.5 — Alert and incident integration

- Define operational alerts for error rates, queue age, failed jobs, provider outages, latency, and security events.
- Define business alerts separately from system alerts.
- Add escalation, acknowledgement, resolution, and post-incident notes.

## Tests required

- Metric/event schema and version tests.
- Correlation and redaction tests.
- Dashboard query permission tests.
- Exception false-positive, suppression, and deduplication tests.
- Job backlog and alert-threshold tests.
- Outcome attribution and incomplete-data tests.

## Exit criteria

- Operators can trace a failed user operation across API, jobs, providers, and AI calls.
- Managers can inspect important exceptions and their evidence.
- AI cost, usage, intervention, success, and failure are measurable.
- Alerts are actionable and do not repeatedly create duplicate work.
- The team can compare the product with Phase 00 baselines.
