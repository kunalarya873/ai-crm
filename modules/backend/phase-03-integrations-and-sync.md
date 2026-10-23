# Backend Phase 03 — Integrations and Synchronisation

## Goal

Connect the selected external applications through reliable adapters and synchronise only the data and actions required by the target workflow.

## Build in this phase

### B03.1 — Connector ports and provider adapters

- Define internal connector interfaces for authentication, read, write, webhook verification, pagination, rate limits, and provider errors.
- Keep provider SDKs and payload shapes inside adapters.
- Return canonical records plus source IDs, source URLs, provider timestamps, and provenance.

### B03.2 — Connection and credential lifecycle

- Implement connect, refresh, test, disconnect, and revoke flows.
- Store encrypted tokens or references to a secret manager.
- Record scopes and provider permissions granted by the customer.
- Prevent disconnected or expired connections from being used for writes.

### B03.3 — Sync jobs and checkpoints

- Implement initial import, incremental sync, webhook ingestion, and scheduled reconciliation.
- Track cursor/checkpoint, last attempt, last success, records processed, and failure reason.
- Use leases so two workers do not process the same sync concurrently.

### B03.4 — Idempotency and conflict handling

- Deduplicate provider events by provider ID and event ID.
- Define field ownership and conflict rules.
- Handle deleted records, permission changes, partial imports, malformed data, rate limits, and provider downtime.
- Use bounded exponential backoff with jitter and a recoverable failed state.

### B03.5 — Webhook and external-write boundaries

- Verify webhook signatures and reject replays.
- Acknowledge webhooks quickly and process them asynchronously.
- Require idempotency keys for external writes.
- Persist request/response metadata without storing unnecessary sensitive payloads.

## Tests required

- Adapter contract tests with provider fixtures.
- Webhook signature and replay tests.
- Duplicate event and retry tests.
- Rate-limit, timeout, permission, malformed-payload, and provider-outage tests.
- Sync resume and reconciliation tests.
- External-write idempotency tests.

## Exit criteria

- The selected integrations can be connected, synchronised, monitored, and disconnected safely.
- Replayed events and jobs do not duplicate internal records or external effects.
- Users and operators can see freshness, scope, failures, retries, and recovery actions.
- Provider-specific failures are converted into stable internal error categories.
- No AI or workflow action depends on an untested connector write path.
