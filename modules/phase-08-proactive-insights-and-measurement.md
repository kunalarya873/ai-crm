# Phase 08 — Proactive Insights and Business-Value Measurement

## Goal

Move from responding to user requests to identifying meaningful exceptions and measuring whether AI and automation improve the business.

## Modules

### M08.1 — Operational event and metric model

- Define events for record changes, activity, task progress, approvals, syncs, AI runs, actions, errors, and outcomes.
- Establish metric definitions, dimensions, time windows, ownership, and data-quality rules.
- Separate observed metrics from forecasts or model-generated scores.

### M08.2 — Dashboards and investigation views

- Show pipeline, follow-up, response, workload, automation, integration, and AI-usage metrics relevant to the target segment.
- Allow users to move from an aggregate change to the underlying records and evidence.
- Mark incomplete or delayed data.

### M08.3 — Exception and anomaly detection

- Detect overdue commitments, inactive opportunities, delayed responses, repeated failures, unusual changes, and missing information.
- Start with transparent rules and thresholds before introducing learned anomaly models.
- Explain why an exception was raised and what evidence supports it.

### M08.4 — Recommendation and alert workflow

- Turn significant exceptions into reviewable work items or notifications.
- Apply severity, ownership, suppression, deduplication, and escalation rules.
- Require approval before any consequential action.

### M08.5 — AI value and cost accounting

- Track model usage cost, human review time, acceptance/edit/rejection rate, task completion, error rate, and outcome proxies.
- Compare assisted and unassisted workflows where an experiment is appropriate.
- Provide a report that links AI activity to business outcomes without claiming causation unsupported by evidence.

## Deliverables

- Business event and metric model.
- Operational dashboards and drill-downs.
- Explainable exception detection.
- Alert-to-work-item flow.
- AI cost, effectiveness, and outcome reporting.

## Dependencies

Phases 01–07 and sufficient pilot data. Metrics should be defined in Phase 00 even if implementation comes later.

## Exit criteria

- Managers can identify important operational problems without manually opening every record.
- Each alert includes evidence, severity, owner, and next step.
- AI cost and human intervention are visible alongside workflow outcomes.
- The team can identify which AI capabilities create value and which create rework or risk.
- False positives and missed exceptions are measured and reviewed.

## Do not build yet

- Black-box predictions that cannot be investigated.
- Automated high-impact decisions based only on an anomaly score.
