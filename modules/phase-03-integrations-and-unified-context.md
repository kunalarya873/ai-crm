# Phase 03 — Integrations and Unified Business Context

## Goal

Connect the few external systems that matter to the validated workflow and make their authorised information available through a consistent, traceable context layer.

## Modules

### M03.1 — Connector framework

- Define connector lifecycle, authentication, scopes, token refresh, configuration, health, and disconnect behaviour.
- Standardise pagination, rate-limit handling, retries, timeouts, webhooks, and polling.
- Separate provider-specific adapters from the canonical application model.

### M03.2 — First-party integrations

- Implement only the integrations selected in Phase 00, such as email/calendar, support, billing, or a source CRM.
- Import the minimum records needed for the target workflow.
- Support source links, provider IDs, sync status, and last-successful-sync information.

### M03.3 — Synchronisation and data quality

- Define create/update ownership for each field and record type.
- Handle conflicts, deleted records, changed permissions, partial syncs, and stale data.
- Make sync failures actionable and prevent repeated writes from creating duplicates.

### M03.4 — Unified customer context

- Resolve identities and relate records across systems using explicit matching rules.
- Provide a context object containing authorised customer records, activities, tasks, documents, and recent changes.
- Include provenance, freshness, confidence, and permission metadata in context items.

### M03.5 — Integration operations

- Add connection health, sync history, error details, retry controls, and manual recovery.
- Provide safe reauthorisation and disconnect flows.
- Record external actions separately from internal record changes.

## Deliverables

- Connector interface and provider adapter pattern.
- Initial production-quality integrations.
- Sync jobs/webhooks and idempotency rules.
- Unified context API with provenance and access filtering.
- Integration health and recovery view.

## Dependencies

Phases 01 and 02. The exact providers and fields must come from Phase 00 research.

## Exit criteria

- The selected external records appear in the correct customer context without cross-tenant leakage.
- A replayed webhook or job does not create duplicate records or actions.
- Rate limits, permission failures, provider downtime, and malformed data produce controlled states.
- Users can identify the source and freshness of important context.
- A connector can be disabled without corrupting existing internal records.

## Do not build yet

- A large marketplace of connectors.
- Unbounded bi-directional synchronisation.
- AI-generated actions against an integration before its write path is tested.
