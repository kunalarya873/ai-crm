# Backend Phase 04 — Search, Knowledge, and Context

## Goal

Provide a backend retrieval layer that can find relevant authorised information and assemble bounded context for users, AI, and workflows.

## Build in this phase

### B04.1 — Knowledge source registry

- Register CRM records, activities, documents, procedures, templates, and imported sources.
- Store visibility, owner, source, version, effective date, freshness, and archival status.
- Define which source types are searchable and which may be supplied to AI.

### B04.2 — Indexing pipeline

- Create asynchronous extraction, chunking/normalisation, indexing, update, and deletion jobs.
- Track source version and indexing status.
- Make indexing repeatable and safe to retry.
- Do not publish incomplete or failed indexing results as current knowledge.

### B04.3 — Permission-aware retrieval

- Apply tenant, record, document, team, and field-level visibility rules at query time.
- Ensure filtered results cannot reveal the existence or metadata of inaccessible content.
- Return provenance, source identifiers, timestamps, freshness, and relevance information.

### B04.4 — Search API

- Implement structured record search and full-text/semantic retrieval only where justified by the use case.
- Support filters for customer, source, owner, type, status, and date.
- Use stable pagination and bounded result limits.
- Return an explicit insufficient-evidence result instead of fabricating completeness.

### B04.5 — Context assembler

- Build a canonical context request for a customer, workflow, task, or action.
- Apply relevance, freshness, permission, token/size, and sensitivity limits.
- Record which context items were supplied to downstream AI or automation.

## Tests required

- Retrieval relevance and freshness tests.
- Permission leakage and inaccessible-result tests.
- Index update, deletion, replay, and failure tests.
- Context-size and sensitive-field filtering tests.
- Provenance and citation completeness tests.

## Exit criteria

- A user can search the selected data sources through a stable backend API.
- AI callers receive only authorised, bounded, source-linked context.
- Index failures and stale sources are visible to operators.
- Updates and deletions do not leave uncontrolled stale results.
- Retrieval quality is measured with a representative evaluation set.
