# Backend Phase 06 — AI Gateway and Copilot Backend

## Goal

Add AI capabilities behind a controlled backend gateway. AI should consume bounded authorised context and return typed, reviewable results rather than direct system commands.

## Build in this phase

### B06.1 — Model/provider gateway

- Define a provider-neutral interface for text generation, structured extraction, embeddings if needed, and model health.
- Centralise timeouts, retries, request limits, provider errors, fallback policy, and cost accounting.
- Store provider/model identifiers and configuration version for every run.

### B06.2 — Prompt and policy versioning

- Store prompt/template versions outside application code where safe and reviewable.
- Associate each AI run with prompt version, model, tools, context references, user, tenant, and feature flag.
- Add policy checks for sensitive data, forbidden actions, output length, and required evidence.

### B06.3 — Structured AI use cases

Implement bounded use cases rather than one unrestricted assistant:

- Customer/activity summary.
- Structured field extraction.
- Next-step recommendation.
- Communication draft.
- Workflow-plan proposal.

Each use case should have a typed request and response schema, confidence/uncertainty fields, evidence references, and a safe fallback.

### B06.4 — Context and tool boundary

- Retrieve context through the Phase 04 context assembler.
- Expose read-only tools first.
- Keep any proposed write as a typed action proposal for Phase 07.
- Enforce tool permissions independently of the model's output.

### B06.5 — AI run records and feedback

- Persist status, latency, token/usage estimates, cost, model/provider, context references, output, validation result, and human feedback.
- Store user edits, acceptance, rejection, and correction without treating them as automatically correct labels.
- Support replay against a fixed evaluation set.

## Tests required

- Provider adapter and timeout tests.
- Structured-output validation tests.
- Prompt/model version tracking tests.
- Permission and sensitive-context tests.
- Unsupported/insufficient-evidence tests.
- AI failure and fallback tests.
- Evaluation tests for groundedness, relevance, extraction, and unsafe output.

## Exit criteria

- AI output is never treated as trusted executable input.
- Every material response records model, prompt version, context references, and outcome.
- Outputs are validated before they reach application code.
- Users can review and correct generated results.
- AI spend, latency, failures, and acceptance/edit/rejection rates are measurable.
