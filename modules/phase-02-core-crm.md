# Phase 02 — Core CRM and Customer Records

## Goal

Build the smallest CRM data model that gives the target team a dependable place to manage customer context and work. This is the system of record for the MVP workflow, not an attempt to reproduce every CRM feature.

## Modules

### M02.1 — Customer and company records

- Implement people/contacts, companies/accounts, relationships, ownership, lifecycle state, and tags.
- Support custom fields only where they are needed by the validated workflow.
- Preserve source references and record provenance when data originates outside the platform.

### M02.2 — Leads, opportunities, and pipeline

- Model the target workflow's lead or opportunity stages.
- Support owner, value or priority, next step, expected date, status, and loss/win reason where relevant.
- Make stage transitions and ownership changes visible in the activity history.

### M02.3 — Conversations, notes, and activities

- Store emails, calls, meetings, messages, notes, and important customer events in a consistent timeline.
- Support manual entry and imported records.
- Avoid duplicating the same activity when an integration is replayed.

### M02.4 — Tasks, reminders, and ownership

- Create tasks with assignee, due date, priority, status, source, dependency, and completion evidence.
- Support follow-up reminders and overdue states.
- Connect tasks to customer records, opportunities, conversations, and workflows.

### M02.5 — Focused CRM user experience

- Build list, detail, timeline, search, task, and workflow views needed by the target user.
- Show provenance and last-updated information.
- Make missing information and stale records visible rather than silently hiding them.

## Deliverables

- Versioned core CRM schema and migrations.
- CRUD APIs with permission checks and validation.
- Customer timeline and task management UI.
- Activity history and duplicate-prevention rules.
- Seeded demo scenario based on the validated workflow.

## Dependencies

Phase 01 tenant, authorisation, audit, and data conventions.

## Exit criteria

- A user can complete the target workflow manually using the product's records and tasks.
- A manager can see ownership, status, next steps, overdue work, and recent activity.
- Every material record change has an actor and timestamp.
- Duplicate activities and invalid state transitions are prevented or clearly surfaced.
- The workflow can be tested end-to-end without any AI dependency.

## Do not build yet

- Every possible CRM object or industry-specific module.
- Predictive lead scoring.
- Automatic outbound communication.
