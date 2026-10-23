# Phase 04 — Knowledge and Search

## Goal

Enable users and later AI features to find relevant, authorised information across CRM records, conversations, documents, and approved organisational knowledge with clear evidence.

## Modules

### M04.1 — Knowledge source registry

- Register documents, procedures, templates, FAQs, CRM records, conversations, and imported knowledge sources.
- Store owner, visibility, source, version, effective date, and archival status.
- Define which sources are eligible for search, retrieval, and AI use.

### M04.2 — Indexing and synchronisation

- Extract text and structured fields from approved sources.
- Track indexing status, source version, chunk or record references, and deletion/update events.
- Ensure access permissions are applied at retrieval time, not only at ingestion time.

### M04.3 — Search and filtering

- Implement keyword and structured search for customer, activity, task, and knowledge records.
- Add filters for tenant, owner, source, date, customer, status, and record type.
- Return source links, snippets, timestamps, and freshness information.

### M04.4 — Context retrieval for AI

- Build a retrieval interface that returns bounded, permission-checked context.
- Prefer direct customer and workflow evidence over generic content.
- Detect insufficient, conflicting, or stale evidence and expose that state to callers.

### M04.5 — Knowledge governance

- Support document review, replacement, archival, and access changes.
- Record who published or changed organisational knowledge.
- Provide an operator view for failed or outdated indexing.

## Deliverables

- Searchable CRM and knowledge index.
- Permission-aware retrieval API.
- Source and provenance display in the UI.
- Index health and governance controls.
- Evaluation set for retrieval relevance and permission correctness.

## Dependencies

Phases 01–03, especially tenant permissions, source provenance, and unified context.

## Exit criteria

- Users can find the records and documents required by the target workflow.
- Search results respect record and document permissions.
- AI retrieval results can be traced to source records or document sections.
- Updates and deletions remove stale results within the defined freshness target.
- Retrieval evaluation identifies both relevance failures and access-control failures.

## Do not build yet

- A completely open enterprise knowledge graph.
- Retrieval without citations or permission checks.
- Automatic publication of unreviewed generated knowledge.
